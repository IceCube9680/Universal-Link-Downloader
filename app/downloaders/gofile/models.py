from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Union


@dataclass
class GofileFile:
    content_id: str
    name: str
    size: Optional[int]
    mime_type: Optional[str]
    download_url: str
    expires_at: Optional[datetime] = None
    md5: Optional[str] = None
    direct_link: Optional[str] = None


@dataclass
class GofileFolder:
    content_id: str
    name: str
    children_count: int = 0
    total_size: int = 0
    files: List[GofileFile] = field(default_factory=list)
    subfolders: List["GofileFolder"] = field(default_factory=list)


@dataclass
class GofileContent:
    content_id: str
    is_folder: bool
    file: Optional[GofileFile] = None
    folder: Optional[GofileFolder] = None

    @property
    def name(self) -> str:
        if self.file:
            return self.file.name
        if self.folder:
            return self.folder.name
        return f"gofile_{self.content_id}"

    @property
    def total_size(self) -> Optional[int]:
        if self.file:
            return self.file.size
        if self.folder:
            return self.folder.total_size
        return None
