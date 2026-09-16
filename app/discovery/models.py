from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DiscoveredLink:
    url: str
    source_url: str
    depth: int = 0
    service_name: str = "Unknown"
    is_supported: bool = False
    domain: str = ""
    is_webpage: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryResult:
    root_urls: List[str]
    links: List[DiscoveredLink] = field(default_factory=list)
    total_discovered: int = 0
    total_supported: int = 0
    total_unsupported: int = 0
    duplicates_count: int = 0
    duration_seconds: float = 0.0

    @property
    def supported_links(self) -> List[DiscoveredLink]:
        return [l for l in self.links if l.is_supported]

    @property
    def unsupported_links(self) -> List[DiscoveredLink]:
        return [l for l in self.links if not l.is_supported]
