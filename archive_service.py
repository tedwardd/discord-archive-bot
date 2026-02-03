import aiohttp
from urllib.parse import quote
from dataclasses import dataclass


@dataclass
class ArchiveResult:
    """Result of an archive lookup or submission."""
    found: bool
    archive_url: str | None = None
    error: str | None = None
    submitted: bool = False


class ArchiveService:
    """Service for interacting with archive.is (archive.today)."""
    
    BASE_URL = "https://archive.today"
    TIMEMAP_URL = "https://archive.today/timemap"
    
    # Browser-like headers to avoid rate limiting
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.HEADERS)
        return self.session
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def check_archive(self, url: str) -> ArchiveResult:
        """
        Check if a URL has been archived on archive.is.
        Returns the most recent archive URL if found.
        """
        session = await self._get_session()
        
        # Use the timemap endpoint to check for existing archives
        check_url = f"{self.TIMEMAP_URL}/{quote(url, safe='')}"
        
        try:
            async with session.get(check_url, allow_redirects=True) as response:
                if response.status == 200:
                    text = await response.text()
                    # Parse the timemap response to find archive URLs
                    # The timemap returns links in a specific format
                    lines = text.strip().split('\n')
                    archive_urls = []
                    
                    for line in lines:
                        if 'archive.is/' in line or 'archive.today/' in line:
                            # Extract URL from the line
                            parts = line.split('<')
                            for part in parts:
                                if 'archive.is/' in part or 'archive.today/' in part:
                                    url_part = part.split('>')[0]
                                    if url_part.startswith('http'):
                                        archive_urls.append(url_part)
                    
                    if archive_urls:
                        # Return the most recent (last) archive
                        return ArchiveResult(found=True, archive_url=archive_urls[-1])
                
                # No archives found
                return ArchiveResult(found=False)
                
        except aiohttp.ClientError as e:
            return ArchiveResult(found=False, error=str(e))
    
    async def check_archive_simple(self, url: str) -> ArchiveResult:
        """
        Simple check using the direct archive.today/url format.
        This is more reliable for checking existing archives.
        """
        session = await self._get_session()
        
        # archive.today/newest/URL redirects to the newest archive if it exists
        check_url = f"{self.BASE_URL}/newest/{url}"
        
        try:
            async with session.get(check_url, allow_redirects=False) as response:
                if response.status == 429:
                    return ArchiveResult(
                        found=False,
                        archive_url=self.get_search_url(url),
                        error="Rate limited by archive.today. Use the link to check manually."
                    )
                
                if response.status in (301, 302, 303, 307, 308):
                    # Redirect means an archive exists
                    location = response.headers.get('Location', '')
                    if location and '/newest/' not in location:
                        return ArchiveResult(found=True, archive_url=location)
                
                # Check if we got a 200 with an actual archive page
                if response.status == 200:
                    # Check the final URL after potential redirects
                    final_url = str(response.url)
                    if '/newest/' not in final_url and 'archive.' in final_url:
                        return ArchiveResult(found=True, archive_url=final_url)
                
                return ArchiveResult(found=False)
                
        except aiohttp.ClientError as e:
            return ArchiveResult(
                found=False, 
                archive_url=self.get_search_url(url),
                error=str(e)
            )
    
    def get_search_url(self, url: str) -> str:
        """Get the URL to search for existing archives."""
        return f"{self.BASE_URL}/{quote(url, safe='')}"
    
    def get_manual_archive_url(self, url: str) -> str:
        """Get the URL for manually archiving a page."""
        return f"{self.BASE_URL}/?run=1&url={quote(url, safe='')}"
    
    async def check_and_archive(self, url: str) -> ArchiveResult:
        """
        Check if a URL is archived. If not, return a link for manual archiving.
        Note: Automatic submission is not possible due to CAPTCHA requirements.
        """
        # Check if it's already archived
        result = await self.check_archive_simple(url)
        
        if result.found or result.error:
            return result
        
        # Not found - provide manual archive link
        # We can't submit automatically due to CAPTCHA
        return ArchiveResult(
            found=False,
            archive_url=self.get_manual_archive_url(url),
            submitted=False
        )
