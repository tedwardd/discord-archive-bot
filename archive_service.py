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
    
    BASE_URL = "https://archive.is"
    TIMEMAP_URL = "https://archive.is/timemap"
    
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; ArchiveBot/1.0)"
                }
            )
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
        Simple check using the direct archive.is/url format.
        This is more reliable for checking existing archives.
        """
        session = await self._get_session()
        
        # archive.is/newest/URL redirects to the newest archive if it exists
        check_url = f"{self.BASE_URL}/newest/{url}"
        
        try:
            async with session.get(check_url, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    # Redirect means an archive exists
                    location = response.headers.get('Location', '')
                    if location and '/newest/' not in location:
                        return ArchiveResult(found=True, archive_url=location)
                
                # Check if we got a 200 with an actual archive page
                if response.status == 200:
                    # Check the final URL after potential redirects
                    final_url = str(response.url)
                    if '/newest/' not in final_url and self.BASE_URL in final_url:
                        return ArchiveResult(found=True, archive_url=final_url)
                
                return ArchiveResult(found=False)
                
        except aiohttp.ClientError as e:
            return ArchiveResult(found=False, error=str(e))
    
    async def submit_archive(self, url: str) -> ArchiveResult:
        """
        Submit a URL to be archived on archive.is.
        Note: This initiates the archiving process but doesn't wait for completion.
        """
        session = await self._get_session()
        
        submit_url = f"{self.BASE_URL}/submit/"
        
        try:
            # First, get the submit page to obtain any necessary tokens
            async with session.get(self.BASE_URL) as response:
                if response.status != 200:
                    return ArchiveResult(
                        found=False, 
                        error="Could not access archive.is",
                        submitted=False
                    )
            
            # Submit the URL for archiving
            data = {"url": url}
            async with session.post(
                submit_url, 
                data=data,
                allow_redirects=False
            ) as response:
                # archive.is typically redirects to the new archive page
                if response.status in (200, 301, 302, 303, 307, 308):
                    location = response.headers.get('Location', '')
                    return ArchiveResult(
                        found=False,
                        archive_url=location if location else None,
                        submitted=True
                    )
                
                return ArchiveResult(
                    found=False,
                    error=f"Unexpected response: {response.status}",
                    submitted=False
                )
                
        except aiohttp.ClientError as e:
            return ArchiveResult(found=False, error=str(e), submitted=False)
    
    async def check_and_archive(self, url: str) -> ArchiveResult:
        """
        Check if a URL is archived, and if not, submit it for archiving.
        """
        # First check if it's already archived
        result = await self.check_archive_simple(url)
        
        if result.found:
            return result
        
        # Not found, try to submit for archiving
        submit_result = await self.submit_archive(url)
        return submit_result
