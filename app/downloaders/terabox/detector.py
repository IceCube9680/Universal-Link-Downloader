import re
import urllib.parse
from typing import List, Optional, Set
from app.downloaders.terabox.models import TeraBoxLinkInfo
from app.utils.url import is_valid_url

TERABOX_DOMAINS = [
    "terabox.com",
    "terabox.app",
    "teraboxapp.com",
    "teraboxurl.com",
    "1024tera.com",
    "1024tera.co",
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
    "4funbox.co",
    "mirrobox.com",
    "mirrorbox.com",
    "momerybox.com",
    "tibibox.com",
    "boxtera.com",
    "terafiles.com",
    "teradownloader.com",
    "terashare.net",
    "terashare.cc",
    "terashare.top",
    "dubox.com",
    "diskwalalink.com"
]

TERABOX_MIRROR_HOSTS = [
    "www.terabox.app",
    "www.1024tera.com",
    "www.1024terabox.com",
    "www.terabox.com",
    "www.teraboxapp.com",
    "www.freeterabox.com",
    "www.4funbox.com",
    "www.4funbox.co",
    "www.1024tera.co",
    "www.nephobox.com",
    "www.mirrobox.com",
    "www.momerybox.com",
    "www.tibibox.com",
    "www.terabox.fun",
    "www.teraboxlink.com",
    "www.terasharelink.com",
    "www.teraboxshare.com"
]


class TeraBoxDetector:
    """
    Dedicated URL detector and normalizer for TeraBox and clone domains.
    Strictly prevents substring false-positives (e.g. literate.org or interaction.com).
    """

    @staticmethod
    def is_terabox_domain(hostname: str) -> bool:
        if not hostname:
            return False
        clean_host = hostname.lower().strip()
        for domain in TERABOX_DOMAINS:
            # Exact match or subdomain match (e.g. www.terabox.com or terabox.com)
            if clean_host == domain or clean_host.endswith(f".{domain}"):
                return True
        return False

    @classmethod
    def is_terabox_url(cls, url: str) -> bool:
        if not url or not is_valid_url(url):
            return False
        try:
            parsed = urllib.parse.urlparse(url.strip())
            if parsed.scheme.lower() not in ("http", "https"):
                return False
            hostname = (parsed.hostname or "").lower().strip()
            return cls.is_terabox_domain(hostname)
        except Exception:
            return False

    @classmethod
    def extract_surl(cls, url: str) -> Optional[str]:
        """
        Extract canonical shorturl key across all supported formats:
        - https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ
        - https://1024tera.com/wap/share/filelist?surl=WEUA8kuiwqs-1piiDAh2TQ
        - https://teraboxapp.com/sharing/link?surl=abc12345
        - https://mirrobox.com/share/mirror999
        - /s/<key>, /sharing/link/<key>, /app/<key>, /file/<key>, /d/<key>
        - Direct path /1abc12345
        """
        if not url:
            return None

        # 1. Query parameters
        match_q = re.search(r'[?&](?:surl|shorturl|code|key|id|shareid)=([a-zA-Z0-9_-]+)', url)
        if match_q:
            return match_q.group(1)

        # 2. Path prefix patterns
        match_path = re.search(r'/(?:s|wap/share/filelist|sharing/link|sharing/init|sharing|share/init|share/list|share|app|d|file|web/share|wap/link|main)/([a-zA-Z0-9_-]+)', url)
        if match_path:
            return match_path.group(1)

        # 3. Path ending directly in 8+ character alphanumeric key or 1-prefixed key
        match_direct = re.search(r'/(1[a-zA-Z0-9_-]{7,}|[a-zA-Z0-9_-]{10,})(?:[/?#]|$)', url)
        if match_direct:
            return match_direct.group(1)

        return None

    @classmethod
    def extract_pwd(cls, url: str) -> Optional[str]:
        """Extract password/extraction code if present."""
        if not url:
            return None
        match = re.search(r'[?&](?:pwd|password|extraction_code)=([a-zA-Z0-9]+)', url)
        return match.group(1) if match else None

    @classmethod
    def get_surl_candidates(cls, surl: str) -> List[str]:
        """
        Return shorturl candidate variations (without prefix '1' first, then with '1').
        """
        if not surl:
            return []
        candidates = []
        if surl.startswith("1") and len(surl) > 1:
            candidates.append(surl[1:])
            candidates.append(surl)
        else:
            candidates.append(surl)
            candidates.append(f"1{surl}")
        return list(dict.fromkeys(candidates))

    @classmethod
    def normalize_url(cls, url: str) -> str:
        """
        Normalize URL:
        - Strip whitespace
        - Standardize scheme to https
        - Extract surl and pwd into canonical structure
        """
        raw = url.strip()
        surl = cls.extract_surl(raw)
        pwd = cls.extract_pwd(raw)
        if not surl:
            return raw

        canonical = f"https://www.terabox.app/sharing/link?surl={surl}"
        if pwd:
            canonical = f"{canonical}&pwd={pwd}"
        return canonical

    @classmethod
    def detect(cls, url: str) -> TeraBoxLinkInfo:
        """
        Perform complete validation and information extraction for a TeraBox link.
        """
        raw = url.strip()
        parsed = urllib.parse.urlparse(raw)
        domain = (parsed.hostname or "").lower()
        surl = cls.extract_surl(raw) or ""
        pwd = cls.extract_pwd(raw)
        candidates = cls.get_surl_candidates(surl) if surl else []
        norm = cls.normalize_url(raw)
        is_valid = bool(surl and cls.is_terabox_domain(domain))

        return TeraBoxLinkInfo(
            raw_url=raw,
            normalized_url=norm,
            surl=surl,
            surl_candidates=candidates,
            domain=domain,
            password=pwd,
            is_valid=is_valid
        )
