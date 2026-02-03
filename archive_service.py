from dataclasses import dataclass
from urllib.parse import quote


@dataclass
class ArchiveLinks:
    """Links for archive.today."""
    search_url: str
    save_url: str


class ArchiveService:
    """Service for generating archive.today links."""
    
    BASE_URL = "https://archive.today"
    
    def get_links(self, url: str) -> ArchiveLinks:
        """Get search and save links for a URL."""
        encoded_url = quote(url, safe='')
        return ArchiveLinks(
            search_url=f"{self.BASE_URL}/{encoded_url}",
            save_url=f"{self.BASE_URL}/?run=1&url={encoded_url}"
        )
    
    async def close(self):
        """No-op for compatibility."""
        pass
