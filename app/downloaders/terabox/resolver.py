import asyncio
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional
import aiohttp

from app.core.config import settings
from app.core.logging import get_logger
from app.downloaders.base import FileMetadata, ResolvedURL
from app.downloaders.generic import DEFAULT_USER_AGENT
from app.downloaders.terabox.client import (
    TeraBoxClient,
    format_terabox_cookie,
    generate_dplogid,
    terabox_client
)
from app.downloaders.terabox.detector import (
    TERABOX_MIRROR_HOSTS,
    TeraBoxDetector
)
from app.downloaders.terabox.exceptions import (
    TeraBoxAuthError,
    TeraBoxCaptchaError,
    TeraBoxInvalidURLError,
    TeraBoxNotFoundError,
    TeraBoxRateLimitError,
    TeraBoxResolutionError
)
from app.downloaders.terabox.models import (
    TeraBoxErrorType,
    TeraBoxFile,
    TeraBoxLinkInfo,
    TeraBoxResolutionResult
)
from app.utils.filename import sanitize_filename
from app.utils.mime import get_mime_type
from app.utils.security import validate_url_security

logger = get_logger("terabox_resolver")


class TeraBoxResolver:
    """
    Production-grade TeraBox link resolver.
    - Resolves links cookie-free first.
    - Validates resolved direct download URLs against SSRF/loopback risks.
    - Supports optional authenticated fallback when configured.
    - Detects expired/invalid session cookies explicitly.
    """

    def __init__(self, client: Optional[TeraBoxClient] = None):
        self.client = client or terabox_client
        self._inflight: Dict[str, asyncio.Task] = {}
        self._coalescing_lock: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        if self._coalescing_lock is None:
            self._coalescing_lock = asyncio.Lock()
        return self._coalescing_lock

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        """
        Main resolver interface for TeraBoxDownloader with request coalescing.
        """
        link_info = TeraBoxDetector.detect(url)
        if not link_info.is_valid or not link_info.surl:
            raise TeraBoxInvalidURLError(f"Could not parse valid TeraBox link from: {url}")

        surl_key = link_info.surl

        async with self._lock:
            if surl_key in self._inflight:
                logger.info("Coalescing concurrent TeraBox resolution for %s", surl_key)
                task = self._inflight[surl_key]
                return await asyncio.shield(task)

            task = asyncio.create_task(self._resolve_internal(link_info, session=session))
            self._inflight[surl_key] = task

        try:
            return await task
        finally:
            async with self._lock:
                self._inflight.pop(surl_key, None)

    async def _resolve_internal(
        self,
        link_info: TeraBoxLinkInfo,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        should_close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            should_close_session = True

        try:
            # 1. Primary Path: Cookie-Free Resolution First
            res = await self._execute_resolution_pipeline(link_info, session=session, use_cookie=False)
            if res.success and res.file and res.file.direct_url:
                await self._validate_direct_url(res.file.direct_url)
                return self._build_resolved_url(res.file, link_info, cookie_header="")

            # 2. Secondary Path: Optional Authenticated Fallback (if configured and usable)
            if self.client.is_cookie_usable:
                logger.info("Attempting optional authenticated fallback resolution for %s", link_info.surl)
                auth_res = await self._execute_resolution_pipeline(link_info, session=session, use_cookie=True)
                if auth_res.success and auth_res.file and auth_res.file.direct_url:
                    from app.downloaders.terabox.credentials import terabox_credentials
                    cookie_val = terabox_credentials.get_terabox_cookie()
                    cookie_hdr = format_terabox_cookie(cookie_val)
                    await self._validate_direct_url(auth_res.file.direct_url)
                    return self._build_resolved_url(auth_res.file, link_info, cookie_header=cookie_hdr)

            # 3. Handle specific typed failure
            if res.error_type == TeraBoxErrorType.NOT_FOUND:
                raise TeraBoxNotFoundError()
            elif res.error_type == TeraBoxErrorType.CAPTCHA_REQUIRED:
                raise TeraBoxCaptchaError()
            elif res.error_type == TeraBoxErrorType.RATE_LIMITED:
                raise TeraBoxRateLimitError()
            elif res.error_type == TeraBoxErrorType.AUTH_EXPIRED:
                raise TeraBoxAuthError()

            raise TeraBoxResolutionError(
                message=res.error_message or "Failed to resolve direct download link across all TeraBox mirrors.",
                user_message=res.error_message or "❌ Could not resolve a direct download link for this TeraBox link.",
                error_type=res.error_type or TeraBoxErrorType.UNKNOWN
            )

        finally:
            if should_close_session:
                await session.close()

    async def _execute_resolution_pipeline(
        self,
        link_info: TeraBoxLinkInfo,
        session: aiohttp.ClientSession,
        use_cookie: bool = False
    ) -> TeraBoxResolutionResult:
        """
        Multi-phase resolution pipeline:
        Phase 1: Web Share HTML Scraping (jsToken & embedded state)
        Phase 2: Official Web & API Endpoints (/share/list, /api/download)
        Phase 3: Public Gateway Fallbacks (only in cookie-free mode)
        """
        last_error_type = TeraBoxErrorType.UNKNOWN
        last_error_msg = None

        # -------------------------------------------------------------
        # Phase 1: Dynamic HTML page scraping
        # -------------------------------------------------------------
        js_token = ""
        bdstoken = ""
        pcftoken = ""
        uk = ""
        shareid = ""
        sign = ""
        timestamp = ""
        primaryid = ""

        for s_key in link_info.surl_candidates:
            for host in TERABOX_MIRROR_HOSTS:
                page_urls = [
                    f"https://{host}/sharing/link?surl={s_key}",
                    f"https://{host}/wap/share/filelist?surl={s_key}"
                ]
                headers = self.client.get_base_headers(host, include_cookie=use_cookie)

                for page_url in page_urls:
                    try:
                        async with session.get(page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                            if resp.status != 200:
                                continue

                            # In mock tests or direct JSON responses
                            try:
                                data = await resp.json()
                                if isinstance(data, dict):
                                    errno = data.get("errno", -1)
                                    if errno in (105, 112, 115, 140, 400141):
                                        return TeraBoxResolutionResult(
                                            success=False,
                                            link_info=link_info,
                                            error_type=TeraBoxErrorType.NOT_FOUND,
                                            error_message="The shared TeraBox file was deleted, cancelled, or does not exist."
                                        )
                                    if errno == 0 and ("list" in data or "file_list" in data):
                                        f = self._parse_file_from_data(data, s_key)
                                        if f and f.direct_url:
                                            return TeraBoxResolutionResult(success=True, file=f, link_info=link_info)
                            except Exception:
                                pass

                            html = await resp.text()

                            # Check for explicit expiration/not found in HTML text
                            if "errno" in html:
                                err_match = re.search(r'["\']?errno["\']?\s*[:=]\s*(\d+)', html)
                                if err_match:
                                    code = int(err_match.group(1))
                                    if code in (105, 112, 115, 140, 400141):
                                        return TeraBoxResolutionResult(
                                            success=False,
                                            link_info=link_info,
                                            error_type=TeraBoxErrorType.NOT_FOUND,
                                            error_message="The shared TeraBox file was deleted, cancelled, or does not exist."
                                        )

                            # Extract jsToken
                            for token_pat in [
                                r'fn%28%22([A-Za-z0-9]+)%22%29',
                                r'fn\s*\(\s*["\']([A-Za-z0-9]+)["\']\s*\)',
                                r'(?:jsToken|token)\s*[:=]\s*["\']([^"\']+)["\']'
                            ]:
                                m = re.search(token_pat, html)
                                if m:
                                    js_token = m.group(1)
                                    break

                            # Extract embedded state JSON
                            for state_pat in [
                                r'templateData\s*=\s*(\{.*?\});\s*</script>',
                                r'yunData\s*=\s*(\{.*?\});\s*</script>',
                                r'locals\s*=\s*(\{.*?\});\s*</script>',
                                r'window\.__INITIAL_DATA__\s*=\s*(\{.*?\});',
                                r'window\.data\s*=\s*(\{.*?\});'
                            ]:
                                sm = re.search(state_pat, html, re.DOTALL)
                                if sm:
                                    try:
                                        t_data = json.loads(sm.group(1))
                                        bdstoken = bdstoken or t_data.get("bdstoken", "")
                                        pcftoken = pcftoken or t_data.get("pcftoken", "")
                                        uk = uk or str(t_data.get("uk", "") or t_data.get("share_uk", ""))
                                        shareid = shareid or str(t_data.get("shareid", "") or t_data.get("share_id", ""))
                                        sign = sign or str(t_data.get("sign", ""))
                                        timestamp = timestamp or str(t_data.get("timestamp", ""))
                                        primaryid = primaryid or str(t_data.get("primaryid", "") or t_data.get("primary_id", ""))

                                        # Check direct file list in template
                                        embedded_list = t_data.get("list") or t_data.get("file_list") or []
                                        if embedded_list and isinstance(embedded_list, list):
                                            f = self._parse_file_from_data({"list": embedded_list}, s_key)
                                            if f and f.direct_url:
                                                return TeraBoxResolutionResult(success=True, file=f, link_info=link_info)
                                    except Exception:
                                        pass

                            if js_token:
                                break
                    except Exception:
                        continue
                if js_token:
                    break

        dp_logid = generate_dplogid(uk)

        # -------------------------------------------------------------
        # Phase 2: Official Web & API Endpoints
        # -------------------------------------------------------------
        for host in TERABOX_MIRROR_HOSTS:
            api_headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"https://{host}/sharing/link?surl={link_info.surl}",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest"
            }
            if use_cookie and self.client.is_cookie_usable:
                from app.downloaders.terabox.credentials import terabox_credentials
                cookie_val = terabox_credentials.get_terabox_cookie()
                cookie_hdr = format_terabox_cookie(cookie_val)
                if cookie_hdr:
                    api_headers["Cookie"] = cookie_hdr

            for s_key in link_info.surl_candidates:
                params = {
                    "app_id": "250528",
                    "web": "1",
                    "channel": "dubox",
                    "clienttype": "0",
                    "clientfrom": "h5",
                    "shorturl": s_key,
                    "root": "1",
                    "page": "1",
                    "num": "100",
                    "order": "time",
                    "desc": "1"
                }
                if js_token:
                    params["jsToken"] = js_token
                if dp_logid:
                    params["dp-logid"] = dp_logid
                if bdstoken:
                    params["bdstoken"] = bdstoken
                if pcftoken:
                    params["pcftoken"] = pcftoken
                if link_info.password:
                    params["pwd"] = link_info.password

                endpoints = [
                    f"https://{host}/share/list?" + urllib.parse.urlencode(params),
                    f"https://{host}/api/share/list?" + urllib.parse.urlencode(params),
                    f"https://{host}/api/share/list?app_id=250528&shorturl={s_key}&root=1",
                    f"https://{host}/wap/share/filelist?app_id=250528&shorturl={s_key}&root=1"
                ]

                for api_url in endpoints:
                    try:
                        async with session.get(api_url, headers=api_headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                            if resp.status != 200:
                                continue

                            data = await resp.json()
                            if not isinstance(data, dict):
                                continue

                            errno = data.get("errno", -1)

                            # Check for session authentication invalidation
                            if errno in (2, -6):
                                if use_cookie:
                                    self.client.mark_cookie_invalid(f"API returned errno {errno}")
                                last_error_type = TeraBoxErrorType.AUTH_EXPIRED
                                continue

                            if errno == 4000020:
                                last_error_type = TeraBoxErrorType.CAPTCHA_REQUIRED
                                continue

                            if errno in (105, 112, 115, 140, 400141):
                                return TeraBoxResolutionResult(
                                    success=False,
                                    link_info=link_info,
                                    error_type=TeraBoxErrorType.NOT_FOUND,
                                    error_message="The shared TeraBox file was deleted, cancelled, or does not exist."
                                )

                            if errno in (4000004, 4000005):
                                last_error_type = TeraBoxErrorType.RATE_LIMITED
                                continue

                            if errno == 0 and ("list" in data or "file_list" in data):
                                file_candidate = self._parse_file_from_data(data, s_key)
                                if file_candidate and file_candidate.direct_url:
                                    return TeraBoxResolutionResult(success=True, file=file_candidate, link_info=link_info)

                                # Attempt ticket retrieval
                                cur_shareid = str(data.get("shareid") or data.get("share_id") or shareid or "")
                                cur_uk = str(data.get("uk") or data.get("share_uk") or uk or "")
                                cur_sign = str(data.get("sign") or sign or "")
                                cur_timestamp = str(data.get("timestamp") or timestamp or "")
                                cur_primaryid = str(data.get("primaryid") or data.get("primary_id") or primaryid or "")

                                file_list = data.get("list") or data.get("file_list") or []
                                if file_list and isinstance(file_list[0], dict):
                                    first_f = file_list[0]
                                    fs_id = first_f.get("fs_id") or first_f.get("fid")
                                    if fs_id:
                                        dlink = await self._fetch_dlink_ticket(
                                            session=session,
                                            host=host,
                                            fs_id=str(fs_id),
                                            shareid=cur_shareid,
                                            uk=cur_uk,
                                            sign=cur_sign,
                                            timestamp=cur_timestamp,
                                            primaryid=cur_primaryid,
                                            js_token=js_token,
                                            dp_logid=dp_logid,
                                            headers=api_headers
                                        )
                                        if dlink:
                                            first_f["dlink"] = dlink
                                            resolved_f = self._parse_file_from_data(data, s_key)
                                            if resolved_f and resolved_f.direct_url:
                                                return TeraBoxResolutionResult(success=True, file=resolved_f, link_info=link_info)
                    except Exception:
                        continue

        # -------------------------------------------------------------
        # Phase 3: Public Gateway Fallbacks (Cookie-free mode only)
        # -------------------------------------------------------------
        if not use_cookie:
            for s_key in link_info.surl_candidates:
                fallback_gateways = [
                    {"method": "GET", "url": f"https://terabox-dl.qtcloud.workers.dev/api/get-info?shorturl={s_key}" + (f"&pwd={link_info.password}" if link_info.password else "")},
                    {"method": "GET", "url": f"https://yt-video-production.up.railway.app/terabox?url=https://terabox.com/s/{s_key}"},
                    {"method": "GET", "url": f"https://terabox-api.gray.stream/api?url=https://terabox.com/s/{s_key}"},
                    {"method": "GET", "url": f"https://terabox.hnn.workers.dev/api/get-info?shorturl={s_key}"},
                    {"method": "GET", "url": f"https://teraboxvideodownloader.nepcoderdevs.workers.dev/?url=https://terabox.com/s/{s_key}"},
                    {"method": "POST", "url": "https://teraboxvideodownloader.nepcoderdevs.workers.dev/", "json": {"url": f"https://terabox.com/s/{s_key}"}},
                    {"method": "GET", "url": f"https://tera.instavideosave.com/?url=https://terabox.com/s/{s_key}"},
                    {"method": "GET", "url": f"https://terabox-downloader-five.vercel.app/api?url=https://terabox.com/s/{s_key}"}
                ]
                for gw in fallback_gateways:
                    try:
                        gw_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
                        gw_method = gw.get("method", "GET")
                        if gw_method == "GET":
                            async with session.get(gw["url"], headers=gw_headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                                if resp.status == 200:
                                    gw_data = await resp.json()
                                    gw_file = self._parse_file_from_gateway(gw_data, s_key)
                                    if gw_file and gw_file.direct_url:
                                        return TeraBoxResolutionResult(success=True, file=gw_file, link_info=link_info)
                        elif gw_method == "POST":
                            async with session.post(gw["url"], json=gw.get("json"), headers=gw_headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                                if resp.status == 200:
                                    gw_data = await resp.json()
                                    gw_file = self._parse_file_from_gateway(gw_data, s_key)
                                    if gw_file and gw_file.direct_url:
                                        return TeraBoxResolutionResult(success=True, file=gw_file, link_info=link_info)
                    except Exception:
                        pass

        return TeraBoxResolutionResult(
            success=False,
            link_info=link_info,
            error_type=last_error_type,
            error_message=last_error_msg
        )

    async def _fetch_dlink_ticket(
        self,
        session: aiohttp.ClientSession,
        host: str,
        fs_id: str,
        shareid: str,
        uk: str,
        sign: str,
        timestamp: str,
        primaryid: str,
        js_token: str,
        dp_logid: str,
        headers: Dict[str, str]
    ) -> Optional[str]:
        """Fetch dlink using secondary ticket request."""
        params = {
            "app_id": "250528",
            "web": "1",
            "channel": "dubox",
            "clienttype": "0",
            "fid_list": f"[{fs_id}]",
            "vip": "2",
            "type": "dlink",
            "product": "share"
        }
        if js_token:
            params["jsToken"] = js_token
        if dp_logid:
            params["dp-logid"] = dp_logid
        if shareid:
            params["shareid"] = shareid
        if uk:
            params["uk"] = uk
        if sign:
            params["sign"] = sign
        if timestamp:
            params["timestamp"] = timestamp
        if primaryid:
            params["primaryid"] = primaryid

        endpoints = [
            f"https://{host}/api/download?" + urllib.parse.urlencode(params),
            f"https://{host}/share/download?" + urllib.parse.urlencode(params),
            f"https://{host}/api/share/download?" + urllib.parse.urlencode(params),
            f"https://{host}/api/v1/download?" + urllib.parse.urlencode(params)
        ]

        for ep in endpoints:
            # Try GET
            try:
                async with session.get(ep, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        dlink = self._extract_dlink_from_ticket_response(data)
                        if dlink:
                            return dlink
            except Exception:
                pass

            # Try POST
            try:
                base_ep = ep.split("?")[0]
                post_headers = dict(headers)
                post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                async with session.post(base_ep, headers=post_headers, data=params, timeout=aiohttp.ClientTimeout(total=6)) as resp_post:
                    if resp_post.status == 200:
                        data = await resp_post.json()
                        dlink = self._extract_dlink_from_ticket_response(data)
                        if dlink:
                            return dlink
            except Exception:
                pass

        return None

    def _extract_dlink_from_ticket_response(self, data: Any) -> Optional[str]:
        if not isinstance(data, dict) or data.get("errno") not in (0, None):
            return None

        dlinks = data.get("dlink")
        if isinstance(dlinks, str) and dlinks:
            return dlinks
        if isinstance(dlinks, list) and dlinks:
            first = dlinks[0]
            if isinstance(first, dict):
                return first.get("dlink") or first.get("url") or first.get("download_url")
            if isinstance(first, str):
                return first

        file_list = data.get("list") or data.get("file_list") or []
        if isinstance(file_list, list) and file_list and isinstance(file_list[0], dict):
            return file_list[0].get("dlink") or file_list[0].get("download_url")

        d_obj = data.get("data")
        if isinstance(d_obj, dict):
            return d_obj.get("dlink") or d_obj.get("url") or d_obj.get("download_url")
        if isinstance(d_obj, list) and d_obj and isinstance(d_obj[0], dict):
            return d_obj[0].get("dlink") or d_obj[0].get("url")

        return None

    def _parse_file_from_data(self, data: Dict[str, Any], surl: str) -> Optional[TeraBoxFile]:
        file_list = data.get("list") or data.get("file_list") or []
        if not file_list or not isinstance(file_list, list) or not isinstance(file_list[0], dict):
            return None

        file_obj = file_list[0]
        filename = sanitize_filename(file_obj.get("server_filename") or file_obj.get("filename") or f"terabox_{surl}.bin")
        filesize = int(file_obj.get("size", 0))
        direct_url = file_obj.get("dlink") or file_obj.get("download_url") or file_obj.get("direct_link") or file_obj.get("url")

        return TeraBoxFile(
            filename=filename,
            size=filesize if filesize > 0 else None,
            mime_type=get_mime_type(filename),
            direct_url=direct_url if isinstance(direct_url, str) and direct_url.startswith("http") else None,
            fs_id=str(file_obj.get("fs_id") or file_obj.get("fid") or ""),
            share_id=str(data.get("shareid") or data.get("share_id") or ""),
            uk=str(data.get("uk") or data.get("share_uk") or "")
        )

    def _parse_file_from_gateway(self, data: Dict[str, Any], surl: str) -> Optional[TeraBoxFile]:
        if not isinstance(data, dict):
            return None

        candidates = []
        if "list" in data and isinstance(data["list"], list):
            candidates.extend(data["list"])
        if "data" in data:
            d = data["data"]
            if isinstance(d, list):
                candidates.extend(d)
            elif isinstance(d, dict):
                candidates.append(d)
        if "files" in data and isinstance(data["files"], list):
            candidates.extend(data["files"])
        if "result" in data and isinstance(data["result"], list):
            candidates.extend(data["result"])
        if not candidates and ("dlink" in data or "download_url" in data or "direct_link" in data or "url" in data):
            candidates.append(data)

        for item in candidates:
            if not isinstance(item, dict):
                continue
            dlink = (
                item.get("dlink")
                or item.get("download_url")
                or item.get("direct_link")
                or item.get("downloadUrl")
                or item.get("direct_url")
                or item.get("url")
            )
            filename = (
                item.get("server_filename")
                or item.get("filename")
                or item.get("fileName")
                or item.get("title")
                or item.get("name")
                or f"terabox_{surl}.bin"
            )
            size = int(item.get("size") or item.get("filesize") or item.get("file_size") or item.get("fileSize") or 0)
            if dlink and isinstance(dlink, str) and dlink.startswith("http"):
                clean_fn = sanitize_filename(filename)
                return TeraBoxFile(
                    filename=clean_fn,
                    size=size if size > 0 else None,
                    mime_type=get_mime_type(clean_fn),
                    direct_url=dlink
                )
        return None

    async def _validate_direct_url(self, direct_url: str) -> None:
        """
        Validate direct download URL scheme, hostname, and SSRF safety before download.
        """
        parsed = urllib.parse.urlparse(direct_url)
        if parsed.scheme.lower() not in ("http", "https"):
            raise TeraBoxResolutionError(f"Resolved direct URL has invalid scheme: '{parsed.scheme}'")
        if not parsed.hostname:
            raise TeraBoxResolutionError("Resolved direct URL is missing a valid hostname.")
        try:
            await validate_url_security(direct_url)
        except Exception as e:
            from app.core.exceptions import SSRFError
            raise SSRFError(f"Resolved download URL failed security check: {e}") from e

    def _build_resolved_url(
        self,
        file: TeraBoxFile,
        link_info: TeraBoxLinkInfo,
        cookie_header: str = ""
    ) -> ResolvedURL:
        metadata = FileMetadata(
            filename=file.filename,
            filesize=file.size,
            mime_type=file.mime_type or get_mime_type(file.filename),
            source_service="TeraBox",
            is_direct=True,
            extra={
                "surl": link_info.surl,
                "fs_id": file.fs_id,
                "share_id": file.share_id,
                "uk": file.uk
            }
        )
        download_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://www.terabox.app/"
        }
        if cookie_header:
            download_headers["Cookie"] = cookie_header

        return ResolvedURL(
            direct_url=file.direct_url or "",
            headers=download_headers,
            metadata=metadata
        )


terabox_resolver = TeraBoxResolver()
