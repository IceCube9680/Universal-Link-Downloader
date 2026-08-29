import asyncio
import ipaddress
import socket
from urllib.parse import urlparse
from typing import List, Union


# Blocked IPv4 and IPv6 Networks (SSRF Protection)
BLOCKED_NETWORKS = [
    # IPv4 Private / Loopback / Link-Local / Reserved / Cloud Metadata
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 Private
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space (Carrier NAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-Local & Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 Private
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.88.99.0/24"),     # 6to4 Relay Anycast
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 Private
    ipaddress.ip_network("198.18.0.0/15"),      # Network Interconnect Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for Future Use
    ipaddress.ip_network("255.255.255.255/32"), # Limited Broadcast

    # IPv6 Special & Private
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),       # IPv4/IPv6 translation
    ipaddress.ip_network("100::/64"),           # Discard-Only Address Block
    ipaddress.ip_network("2001::/23"),          # IETF Protocol Assignments
    ipaddress.ip_network("2001:db8::/32"),      # Documentation
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-Local Unicast
    ipaddress.ip_network("ff00::/8"),           # Multicast
]


class SSRFProtectionError(Exception):
    """Raised when a URL or resolved IP violates SSRF protection rules."""
    pass


def is_ip_blocked(ip: Union[str, ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """
    Check whether an IP address belongs to any blocked/private/internal/metadata network.
    Handles IPv4-mapped IPv6 addresses as well.
    """
    if isinstance(ip, str):
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return True  # Invalid IP representation is blocked
    else:
        ip_obj = ip

    # If it is an IPv4-mapped IPv6 address (e.g., ::ffff:127.0.0.1), unwrap to IPv4
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped

    for network in BLOCKED_NETWORKS:
        try:
            if ip_obj in network:
                return True
        except TypeError:
            # Different IP version comparison
            continue

    return False


async def resolve_hostname_ips(hostname: str, port: int = 80) -> List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """
    Resolve all IP addresses for a given hostname asynchronously.
    """
    loop = asyncio.get_running_loop()
    try:
        addrinfo = await loop.getaddrinfo(
            hostname,
            port,
            proto=socket.IPPROTO_TCP,
            flags=socket.AI_ADDRCONFIG
        )
    except socket.gaierror as e:
        raise SSRFProtectionError(f"Failed to resolve host '{hostname}': {e}") from e

    resolved_ips = []
    for entry in addrinfo:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            resolved_ips.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue

    if not resolved_ips:
        raise SSRFProtectionError(f"No IP addresses found for host '{hostname}'")

    return resolved_ips


async def validate_url_security(url: str) -> None:
    """
    Validate that the URL's scheme, hostname, and resolved IP addresses do not target
    forbidden internal or private endpoints.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFProtectionError(f"Disallowed protocol scheme: '{scheme}'. Only HTTP and HTTPS are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFProtectionError("URL is missing a valid hostname.")

    # Lowercase and strip whitespace
    hostname = hostname.lower().strip()

    # Block well-known localhost aliases
    if hostname in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
        raise SSRFProtectionError(f"Access to '{hostname}' is forbidden.")

    # If hostname is a literal IP address
    try:
        literal_ip = ipaddress.ip_address(hostname)
        if is_ip_blocked(literal_ip):
            raise SSRFProtectionError(f"Access to private/internal IP address {literal_ip} is blocked.")
        return
    except ValueError:
        # Not a literal IP, continue to DNS resolution
        pass

    # Resolve domain name and check all returned IPs
    port = parsed.port or (443 if scheme == "https" else 80)
    resolved_ips = await resolve_hostname_ips(hostname, port)
    for ip in resolved_ips:
        if is_ip_blocked(ip):
            raise SSRFProtectionError(f"Host '{hostname}' resolved to blocked/internal IP {ip}.")
