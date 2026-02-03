import aiohttp
from dataclasses import dataclass
from urllib.parse import quote


@dataclass
class ArchiveResult:
    """Result from archive services."""
    # Wayback Machine results
    wayback_url: str | None = None
    wayback_saved: bool = False
    wayback_error: str | None = None
    
    # archive.today links (always provided)
    archive_today_search: str | None = None
    archive_today_save: str | None = None


class ArchiveService:
    """Service for Wayback Machine API and archive.today links."""
    
    WAYBACK_AVAILABLE_API = "https://archive.org/wayback/available"
    WAYBACK_SAVE_URL = "https://web.archive.org/save"
    ARCHIVE_TODAY_URL = "https://archive.today"
    
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "ArchiveBot/1.0 (Discord Bot)"},
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self.session
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _get_archive_today_links(self, url: str) -> tuple[str, str]:
        """Get archive.today search and save links."""
        encoded_url = quote(url, safe='')
        return (
            f"{self.ARCHIVE_TODAY_URL}/{encoded_url}",
            f"{self.ARCHIVE_TODAY_URL}/?run=1&url={encoded_url}"
        )
    
    async def check_wayback(self, url: str) -> tuple[str | None, str | None]:
        """
        Check if URL exists in Wayback Machine.
        Returns (archive_url, error).
        """
        session = await self._get_session()
        
        try:
            async with session.get(
                self.WAYBACK_AVAILABLE_API,
                params={"url": url}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    snapshot = data.get("archived_snapshots", {}).get("closest")
                    if snapshot and snapshot.get("available"):
                        return snapshot.get("url"), None
                return None, None
        except Exception as e:
            return None, str(e)
    
    async def save_wayback(self, url: str) -> tuple[str | None, bool, str | None]:
        """
        Submit URL to Wayback Machine for archiving.
        Returns (archive_url, success, error).
        """
        session = await self._get_session()
        save_url = f"{self.WAYBACK_SAVE_URL}/{url}"
        
        try:
            async with session.get(save_url, allow_redirects=True) as response:
                if response.status == 200:
                    # The final URL after redirects is the archived page
                    final_url = str(response.url)
                    if "web.archive.org/web/" in final_url:
                        return final_url, True, None
                    return None, True, None
                elif response.status == 429:
                    return None, False, "Wayback Machine rate limit reached"
                else:
                    return None, False, f"Wayback returned status {response.status}"
        except Exception as e:
            return None, False, str(e)
    
    async def get_archive(self, url: str) -> ArchiveResult:
        """
        Check Wayback Machine and provide archive.today links.
        Attempts to find/create Wayback archive, always includes archive.today fallback.
        """
        # Get archive.today links (no API call needed)
        at_search, at_save = self._get_archive_today_links(url)
        
        # Check Wayback Machine for existing archive
        wayback_url, check_error = await self.check_wayback(url)
        
        if wayback_url:
            return ArchiveResult(
                wayback_url=wayback_url,
                archive_today_search=at_search,
                archive_today_save=at_save
            )
        
        # No existing archive - try to save to Wayback
        wayback_url, saved, save_error = await self.save_wayback(url)
        
        return ArchiveResult(
            wayback_url=wayback_url,
            wayback_saved=saved,
            wayback_error=check_error or save_error,
            archive_today_search=at_search,
            archive_today_save=at_save
        )
