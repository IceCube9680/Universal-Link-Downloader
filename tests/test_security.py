import ipaddress
import pytest
from unittest.mock import AsyncMock, patch

from app.utils.security import (
    is_ip_blocked,
    validate_url_security,
    SSRFProtectionError
)


def test_blocked_ips():
    # Loopback
    assert is_ip_blocked("127.0.0.1") is True
    assert is_ip_blocked("127.0.1.1") is True
    assert is_ip_blocked("::1") is True

    # Private RFC 1918
    assert is_ip_blocked("10.0.0.5") is True
    assert is_ip_blocked("172.16.0.1") is True
    assert is_ip_blocked("172.31.255.255") is True
    assert is_ip_blocked("192.168.1.1") is True

    # Cloud metadata & link-local
    assert is_ip_blocked("169.254.169.254") is True
    assert is_ip_blocked("169.254.1.1") is True

    # IPv6 private/link-local
    assert is_ip_blocked("fe80::1") is True
    assert is_ip_blocked("fc00::1") is True

    # Public IPs
    assert is_ip_blocked("8.8.8.8") is False
    assert is_ip_blocked("1.1.1.1") is False
    assert is_ip_blocked("142.250.190.46") is False


@pytest.mark.asyncio
async def test_disallowed_protocols():
    with pytest.raises(SSRFProtectionError, match="Disallowed protocol scheme"):
        await validate_url_security("file:///etc/passwd")

    with pytest.raises(SSRFProtectionError, match="Disallowed protocol scheme"):
        await validate_url_security("ftp://example.com/file.zip")

    with pytest.raises(SSRFProtectionError, match="Disallowed protocol scheme"):
        await validate_url_security("ssh://root@127.0.0.1")


@pytest.mark.asyncio
async def test_literal_ip_blocking():
    with pytest.raises(SSRFProtectionError, match="blocked"):
        await validate_url_security("http://127.0.0.1:8080/data")

    with pytest.raises(SSRFProtectionError, match="blocked"):
        await validate_url_security("https://169.254.169.254/latest/meta-data")


@pytest.mark.asyncio
async def test_hostname_ssrf_blocking(monkeypatch):
    # Mock DNS resolution to return private IP for an internal host
    async def mock_resolve(hostname, port=80):
        return [ipaddress.ip_address("10.0.0.15")]

    monkeypatch.setattr("app.utils.security.resolve_hostname_ips", mock_resolve)

    with pytest.raises(SSRFProtectionError, match="resolved to blocked/internal IP"):
        await validate_url_security("https://internal.corp/secret.pdf")


@pytest.mark.asyncio
async def test_safe_public_domain(monkeypatch):
    async def mock_resolve(hostname, port=80):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr("app.utils.security.resolve_hostname_ips", mock_resolve)

    # Should not raise exception
    await validate_url_security("https://example.com/file.zip")
