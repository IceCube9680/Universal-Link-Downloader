import asyncio
import re
import random
import urllib.parse
import json
from typing import Optional, Dict, Any, List
import aiohttp

from app.core.config import settings
from app.core.constants import ServiceType
from app.core.exceptions import DownloaderResolutionError
from app.core.logging import get_logger
from app.downloaders.base import (
    BaseDownloader,
    DownloadResult,
    FileMetadata,
    ProgressCallback,
    ResolvedURL
)
from app.downloaders.generic import GenericHTTPDownloader, DEFAULT_USER_AGENT
from app.utils.filename import sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("terabox_downloader")

TERABOX_DOMAINS = [
    "terabox.com",
    "terabox.app",
    "teraboxapp.com",
    "teraboxurl.com",
    "1024tera.com",
    "1024terabox.com",
    "teraboxshare.com",
    "teraboxlink.com",
    "terasharefile.com",
    "terafileshare.com",
    "terasharelink.com",
    "terabox.fun",
    "terabox.club",
    "terabox.me",
    "terabox.tech",
    "terabox.link",
    "teradrive.com",
    "nephobox.com",
    "freeterabox.com",
    "4funbox.com",
    "mirrobox.com",
    "mirrorbox.com",
    "momerybox.com",
    "tibibox.com",
    "boxtera.com",
    "terafiles.com",
    "teradownloader.com",
    "terashare.net",
    "terashare.cc",
]


def generate_dplogid(uk: str = "") -> str:
    session_id = str(random.randint(100000, 999999))
    user_id = str(uk) if (uk and len(str(uk)) == 10) else f"00{random.randint(10000000, 99999999)}"
    count_id = "0001"
    return f"{session_id}{user_id}{count_id}"


def format_terabox_cookie(cookie_raw: Optional[str]) -> str:
    if not cookie_raw:
        return ""
    cookie_str = str(cookie_raw).strip().strip('"\'').strip()
    if not cookie_str:
        return ""
    if "ndus=" not in cookie_str and "=" not in cookie_str:
        cookie_str = f"ndus={cookie_str}"
    if "lang=" not in cookie_str:
        cookie_str = f"{cookie_str}; lang=en"
    return cookie_str


class TeraBoxDownloader(BaseDownloader):
    name: str = ServiceType.TERABOX.value
    priority: int = 100
    domain_patterns = TERABOX_DOMAINS

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_surl(self, url: str) -> Optional[str]:
        """
        Extract TeraBox shorturl key across all clone and mirror link variations:
        - https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ
        - https://teraboxshare.com/s/1jo_gPZiIhpMwKGFwFPPgvQ
        - https://terabox.com/s/1abc12345
        - https://1024tera.com/s/1xyz987
        - https://www.1024tera.com/wap/share/filelist?surl=WEUA8kuiwqs-1piiDAh2TQ
        - https://teraboxapp.com/sharing/link?surl=abc12345
        - https://diskwala.com/wap/share/filelist?surl=...
        - https://mirrobox.com/s/abc12345
        - https://teraboxurl.com/1abc12345
        """
        # Format 1: ?surl=<key> or &shorturl=<key> or ?code=<key> or ?key=<key>
        match_q = re.search(r'[?&](?:surl|shorturl|code|key|id)=([a-zA-Z0-9_-]+)', url)
        if match_q:
            return match_q.group(1)

        # Format 2: /s/<key>, /wap/share/filelist/<key>, /sharing/link/<key>, /app/<key>, /d/<key>, /file/<key>
        match = re.search(r'/(?:s|wap/share/filelist|sharing/link|app|d|file)/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)

        # Format 3: /sharing/<key> or /share/<key>
        match_share = re.search(r'/(?:sharing|share)/([a-zA-Z0-9_-]+)', url)
        if match_share:
            return match_share.group(1)

        # Format 4: Path ending directly in surl code e.g. /1abc12345 or /WEUA8kuiwqs-1piiDAh2TQ
        match_direct = re.search(r'/([1a-zA-Z0-9_-]{12,})(?:[/?#]|$)', url)
        if match_direct:
            return match_direct.group(1)

        return None

    def _get_surl_candidates(self, surl: str) -> List[str]:
        """
        Return shorturl candidate variations (stripped '1' first, then original with '1').
        """
        candidates = []
        if surl.startswith("1") and len(surl) > 1:
            candidates.append(surl[1:])
            candidates.append(surl)
        else:
            candidates.append(surl)
            candidates.append(f"1{surl}")
        return list(dict.fromkeys(candidates))

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not retrieve TeraBox metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        surl = self.extract_surl(url)
        should_close = False
        if session is None:
            session = aiohttp.ClientSession()
            should_close = True

        if not surl:
            # Try following redirects to see if target URL contains surl
            try:
                async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    final_url = str(resp.url)
                    surl = self.extract_surl(final_url)
            except Exception:
                pass

        if not surl:
            if should_close:
                await session.close()
            raise DownloaderResolutionError(f"Could not parse TeraBox surl from: {url}")

        surl_candidates = self._get_surl_candidates(surl)
        cookie_header = format_terabox_cookie(settings.TERABOX_COOKIE)

        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        if cookie_header:
            base_headers["Cookie"] = cookie_header

        last_error = None
        need_verify = False
        expired_count = 0

        try:
            # 1. Attempt dynamic session handshake by scraping jsToken & templateData from share page
            js_token = ""
            bdstoken = ""
            pcftoken = ""
            uk = ""

            hosts = [
                "www.terabox.app",
                "www.1024tera.com",
                "www.terabox.com",
                "www.freeterabox.com"
            ]

            for s_key in surl_candidates:
                for host in hosts:
                    page_url = f"https://{host}/sharing/link?surl={s_key}"
                    try:
                        async with session.get(page_url, headers=base_headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status == 200:
                                # In mock unit tests or json-direct responses, resp.json() might have list directly
                                try:
                                    data = await resp.json()
                                    if isinstance(data, dict) and data.get("errno") == 0 and "list" in data:
                                        return self._parse_file_list(data, s_key, cookie_header)
                                except Exception:
                                    pass

                                html = await resp.text()
                                # Check jsToken
                                js_match = re.search(r'fn%28%22([A-Za-z0-9]+)%22%29', html)
                                if not js_match:
                                    js_match = re.search(r'jsToken\s*=\s*["\']([^"\']+)["\']', html)
                                if js_match:
                                    js_token = js_match.group(1)

                                # Check templateData
                                t_match = re.search(r'templateData\s*=\s*(\{.*?\});\s*</script>', html, re.DOTALL)
                                if t_match:
                                    try:
                                        t_data = json.loads(t_match.group(1))
                                        bdstoken = t_data.get("bdstoken", "")
                                        pcftoken = t_data.get("pcftoken", "")
                                        uk = str(t_data.get("uk", ""))
                                    except Exception:
                                        pass

                                if js_token:
                                    break
                    except Exception as e:
                        last_error = e
                        continue
                if js_token:
                    break

            dp_logid = generate_dplogid(uk)

            # 2. Query official share/list with full session parameters across all surl candidates
            for host in hosts:
                api_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Referer": f"https://{host}/sharing/link?surl={surl}",
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest"
                }
                if cookie_header:
                    api_headers["Cookie"] = cookie_header

                for s_key in surl_candidates:
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

                    endpoints = [
                        f"https://{host}/share/list?" + urllib.parse.urlencode(params),
                        f"https://{host}/api/share/list?app_id=250528&shorturl={s_key}&root=1",
                        f"https://{host}/share/list?app_id=250528&shorturl={s_key}&root=1"
                    ]

                    for api_url in endpoints:
                        try:
                            async with session.get(api_url, headers=api_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json()
                                if not isinstance(data, dict):
                                    continue

                                errno = data.get("errno", -1)
                                if errno == 4000020:
                                    need_verify = True
                                    continue

                                if errno in (105, 112, 115, 140):
                                    expired_count += 1
                                    continue

                                if errno == 0 and "list" in data:
                                    return self._parse_file_list(data, s_key, cookie_header)
                        except DownloaderResolutionError:
                            raise
                        except Exception as e:
                            last_error = e
                            continue

            if need_verify:
                raise DownloaderResolutionError(
                    "TeraBox security verification required for this file.\n\n"
                    "The shared link is protected by captcha or restricted by TeraBox. "
                    "Make sure your `TERABOX_COOKIE` in `.env` is a fresh `ndus` cookie from your logged-in account, and restart the bot."
                )

            if expired_count > 0:
                raise DownloaderResolutionError("TeraBox link has expired, was cancelled, or does not exist.")

            raise DownloaderResolutionError(
                f"Failed to resolve TeraBox link across all mirrors. "
                f"({str(last_error) if last_error else 'Link may be expired or private'})"
            )

        finally:
            if should_close:
                await session.close()

    def _parse_file_list(self, data: Dict[str, Any], surl: str, cookie_header: str) -> ResolvedURL:
        file_list = data.get("list", [])
        if not file_list:
            raise DownloaderResolutionError("No files found in this TeraBox folder.")

        file_obj = file_list[0]
        filename = sanitize_filename(file_obj.get("server_filename") or f"terabox_{surl}.bin")
        filesize = int(file_obj.get("size", 0))
        direct_url = file_obj.get("dlink")

        if not direct_url:
            raise DownloaderResolutionError("TeraBox returned file entry without direct download link.")

        metadata = FileMetadata(
            filename=filename,
            filesize=filesize if filesize > 0 else None,
            mime_type=get_mime_type(filename),
            source_service=self.name,
            is_direct=True,
            extra={"surl": surl}
        )
        download_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://www.terabox.app/"
        }
        if cookie_header:
            download_headers["Cookie"] = cookie_header

        return ResolvedURL(
            direct_url=direct_url,
            headers=download_headers,
            metadata=metadata
        )

    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        resolved = await self.resolve(url, session=session)
        final_fn = custom_filename or (resolved.metadata.filename if resolved.metadata else None)

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers=resolved.headers)
            should_close = True

        try:
            return await self._generic.download(
                url=resolved.direct_url,
                destination_dir=destination_dir,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                session=session,
                custom_filename=final_fn,
                headers=resolved.headers
            )
        finally:
            if should_close:
                await session.close()
