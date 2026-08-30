import asyncio
import json
import os
import shutil
import time
from typing import Any, Dict, Optional
import aiohttp

from app.core.config import settings
from app.core.logging import get_logger
from app.downloaders.generic import DEFAULT_USER_AGENT
from app.downloaders.gofile.exceptions import (
    GofileError,
    GofileExpiredContentError,
    GofileNotFoundError,
    GofilePrivateContentError,
    GofileRateLimitError,
    GofileResolutionError
)

logger = get_logger("gofile_client")

API_BASE_URL = "https://api.gofile.io"
WT_SCRIPT_URL = "https://gofile.io/js/wt.obf.js"
WT_CACHE_TTL_SECONDS = 7200  # 2 hours
TOKEN_CACHE_FILE = "data/gofile_token.txt"


class GoFileClient:
    """
    Asynchronous client for GoFile API (https://api.gofile.io).
    Handles token provisioning, WT token generation, rate limit detection, and content queries.
    """

    def __init__(self):
        self._cached_token: Optional[str] = None
        self._cached_wt_js: Optional[str] = None
        self._cached_wt_time: float = 0.0

    def _get_configured_token(self) -> Optional[str]:
        # Priority: GOFILE_API_TOKEN -> GOFILE_TOKEN -> persisted token -> in-memory
        if settings.GOFILE_API_TOKEN and settings.GOFILE_API_TOKEN.strip():
            return settings.GOFILE_API_TOKEN.strip()
        if settings.GOFILE_TOKEN and settings.GOFILE_TOKEN.strip():
            return settings.GOFILE_TOKEN.strip()
        return None

    def _read_persisted_token(self) -> Optional[str]:
        cfg = self._get_configured_token()
        if cfg:
            return cfg
        if os.path.exists(TOKEN_CACHE_FILE):
            try:
                with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                    t = f.read().strip()
                    if t:
                        return t
            except Exception:
                pass
        return None

    def _save_persisted_token(self, token: str) -> None:
        try:
            os.makedirs(os.path.dirname(TOKEN_CACHE_FILE) or ".", exist_ok=True)
            with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(token.strip())
        except Exception:
            pass

    async def get_token(self, session: aiohttp.ClientSession, force_refresh: bool = False) -> str:
        """
        Get active token (configured, cached, or newly provisioned guest account).
        """
        configured = self._get_configured_token()
        if configured:
            return configured

        if not force_refresh:
            if self._cached_token:
                return self._cached_token
            persisted = self._read_persisted_token()
            if persisted:
                self._cached_token = persisted
                return persisted

        # Provision new guest account token
        return await self.create_account(session)

    async def create_account(self, session: aiohttp.ClientSession) -> str:
        """
        Create a new guest account token via POST https://api.gofile.io/accounts.
        """
        timeout = settings.GOFILE_API_TIMEOUT or 30
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Origin": "https://gofile.io",
            "Referer": "https://gofile.io/",
            "Accept": "application/json, text/plain, */*"
        }

        try:
            async with session.post(
                f"{API_BASE_URL}/accounts",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status == 429:
                    retry_after = self._parse_retry_after(resp)
                    persisted = self._read_persisted_token()
                    if persisted:
                        self._cached_token = persisted
                        return persisted
                    raise GofileRateLimitError(
                        "GoFile accounts endpoint rate limited. Please try again shortly.",
                        retry_after=retry_after
                    )

                if resp.status in (200, 201):
                    data = await resp.json()
                    if isinstance(data, dict) and data.get("status") == "ok" and "data" in data:
                        token = data["data"].get("token")
                        if token:
                            self._cached_token = token
                            self._save_persisted_token(token)
                            return token

                persisted = self._read_persisted_token()
                if persisted:
                    self._cached_token = persisted
                    return persisted

                raise GofileResolutionError(f"GoFile account creation returned unexpected status HTTP {resp.status}")

        except (GofileRateLimitError, GofileResolutionError):
            raise
        except Exception as e:
            persisted = self._read_persisted_token()
            if persisted:
                self._cached_token = persisted
                return persisted
            raise GofileResolutionError(f"Failed to connect to GoFile account API: {e}") from e

    async def _get_wt_script(self, session: aiohttp.ClientSession) -> Optional[str]:
        now = time.time()
        if self._cached_wt_js and (now - self._cached_wt_time < WT_CACHE_TTL_SECONDS):
            return self._cached_wt_js

        try:
            async with session.get(
                WT_SCRIPT_URL,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if "generateWT" in text or len(text) > 500:
                        self._cached_wt_js = text
                        self._cached_wt_time = now
                        return text
        except Exception as e:
            logger.debug("Failed to fetch wt.obf.js: %s", e)

        return self._cached_wt_js

    async def generate_website_token(self, token: str, session: aiohttp.ClientSession) -> str:
        """
        Generate the X-Website-Token header using Node.js and wt.obf.js.
        """
        wt_js = await self._get_wt_script(session)
        if not wt_js or not shutil.which("node"):
            return ""

        node_script = f"""
const vm = require('vm');
const code = {json.dumps(wt_js)};
const context = {{
    console: {{ log: () => {{}}, error: () => {{}} }},
    Math: Math,
    Date: Date,
    String: String,
    Array: Array,
    Object: Object,
    RegExp: RegExp,
    parseInt: parseInt,
    parseFloat: parseFloat,
    decodeURIComponent: decodeURIComponent,
    encodeURIComponent: encodeURIComponent,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    performance: {{ timeOrigin: Date.now(), now: () => Date.now() }},
    navigator: {{
        userAgent: {json.dumps(DEFAULT_USER_AGENT)},
        language: 'en-US'
    }},
    location: {{ hostname: 'gofile.io', protocol: 'https:' }},
    document: {{}},
    window: {{}},
    globalThis: {{}}
}};
context.window = context;
context.globalThis = context;
context.self = context;

try {{
    const script = new vm.Script(code);
    script.runInNewContext(context, {{ timeout: 3000 }});
    if (typeof context.generateWT === 'function') {{
        const wt = context.generateWT({json.dumps(token)});
        process.stdout.write(String(wt));
    }}
}} catch (e) {{}}
"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "-e", node_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=4.0)
            return stdout.decode().strip()
        except Exception as e:
            logger.debug("WT token generation failed: %s", e)
            return ""

    async def get_content(
        self,
        content_id: str,
        password: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None
    ) -> Dict[str, Any]:
        """
        Query GoFile content endpoint: GET https://api.gofile.io/contents/{content_id}
        """
        should_close = False
        if session is None:
            session = aiohttp.ClientSession()
            should_close = True

        timeout = settings.GOFILE_API_TIMEOUT or 30

        try:
            token = await self.get_token(session)

            for attempt in range(2):
                wt = await self.generate_website_token(token, session)

                url = f"{API_BASE_URL}/contents/{content_id}?page=1&pageSize=100&sortField=name&sortDirection=1"
                if password:
                    url += f"&password={password}"

                headers = {
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://gofile.io",
                    "Referer": f"https://gofile.io/d/{content_id}",
                    "Accept": "application/json, text/plain, */*"
                }
                if wt:
                    headers["X-Website-Token"] = wt
                    headers["X-BL"] = "en-US"

                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status == 404:
                        raise GofileNotFoundError(f"GoFile content '{content_id}' not found.")

                    if resp.status == 429:
                        retry_after = self._parse_retry_after(resp)
                        raise GofileRateLimitError(
                            "GoFile API rate limit reached. Please wait before retrying.",
                            retry_after=retry_after
                        )

                    if resp.status == 401 and attempt == 0:
                        # Refresh guest token
                        token = await self.get_token(session, force_refresh=True)
                        continue

                    if resp.status != 200:
                        raise GofileResolutionError(f"GoFile API returned HTTP {resp.status}")

                    data = await resp.json()
                    status = data.get("status")

                    if status in ("error-token", "error-wrongToken") and attempt == 0:
                        token = await self.get_token(session, force_refresh=True)
                        continue

                    if status == "error-rateLimit":
                        raise GofileRateLimitError("GoFile rate limit reached. Please wait before retrying.")

                    if status == "error-notFound":
                        raise GofileNotFoundError(f"GoFile content '{content_id}' was not found.")

                    if status == "error-passwordRequired":
                        raise GofilePrivateContentError("This GoFile content is protected by a password.")

                    if status == "error-notPremium":
                        raise GofileResolutionError(
                            "GoFile requires a premium account or website token verification for this content."
                        )

                    if status != "ok" or "data" not in data:
                        raise GofileResolutionError(f"GoFile API error response: {status}")

                    return {
                        "data": data["data"],
                        "token": token
                    }

            raise GofileResolutionError(f"Failed to query GoFile content '{content_id}' after retry attempts.")

        finally:
            if should_close:
                await session.close()

    def _parse_retry_after(self, resp: aiohttp.ClientResponse) -> Optional[int]:
        val = resp.headers.get("Retry-After")
        if val and val.isdigit():
            return int(val)
        return None


gofile_client = GoFileClient()
