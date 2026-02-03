import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright, Browser, Page
from dataclasses import dataclass


@dataclass
class RenderResult:
    """Result from the archive.today renderer."""
    success: bool
    archive_url: str | None = None
    error: str | None = None


class ArchiveRenderer:
    """
    Browser-based renderer for archive.today that attempts to solve CAPTCHAs.
    Requires SOLVECAPTCHA_API_KEY environment variable for SolveCaptcha service.
    """
    
    ARCHIVE_URL = "https://archive.today"
    
    def __init__(self):
        self.browser: Browser | None = None
        self.playwright = None
        self.captcha_api_key = os.getenv("SOLVECAPTCHA_API_KEY")
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    async def _ensure_browser(self):
        """Ensure browser is started."""
        if self.browser is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
    
    async def close(self):
        """Close the browser."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        self.executor.shutdown(wait=False)
    
    def _solve_hcaptcha_sync(self, site_key: str, page_url: str) -> str | None:
        """
        Synchronous hCaptcha solver using SolveCaptcha.
        Called in executor to avoid blocking.
        """
        try:
            from solvecaptcha import SolveCaptcha
            
            solver = SolveCaptcha(self.captcha_api_key)
            result = solver.hcaptcha(
                sitekey=site_key,
                url=page_url
            )
            return result.get('code')
        except Exception as e:
            print(f"SolveCaptcha error: {e}")
            return None
    
    async def _solve_hcaptcha(self, page: Page, site_key: str) -> str | None:
        """
        Solve hCaptcha using SolveCaptcha service.
        Returns the solution token or None if failed.
        """
        if not self.captcha_api_key:
            return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._solve_hcaptcha_sync,
            site_key,
            page.url
        )
    
    async def _check_and_solve_captcha(self, page: Page) -> bool:
        """
        Check for CAPTCHA on page and attempt to solve it.
        Returns True if no CAPTCHA or successfully solved.
        """
        try:
            # Check for hCaptcha iframe
            hcaptcha_frame = page.frame_locator("iframe[src*='hcaptcha']")
            if await hcaptcha_frame.locator("body").count() > 0:
                # Find the sitekey
                sitekey_element = await page.query_selector("[data-sitekey]")
                if sitekey_element:
                    site_key = await sitekey_element.get_attribute("data-sitekey")
                    if site_key:
                        print(f"Found hCaptcha with sitekey: {site_key}")
                        
                        solution = await self._solve_hcaptcha(page, site_key)
                        if solution:
                            # Inject the solution
                            await page.evaluate(f"""
                                document.querySelector('[name="h-captcha-response"]').value = '{solution}';
                                document.querySelector('[name="g-recaptcha-response"]').value = '{solution}';
                            """)
                            
                            # Submit the form
                            await page.click('input[type="submit"]')
                            await page.wait_for_load_state("networkidle", timeout=30000)
                            return True
                        else:
                            return False
            
            return True  # No CAPTCHA found
            
        except Exception as e:
            print(f"CAPTCHA check error: {e}")
            return True  # Continue anyway
    
    async def render_archive(self, url: str, timeout: int = 120000) -> RenderResult:
        """
        Navigate to archive.today and attempt to archive/find the URL.
        
        Args:
            url: The URL to archive
            timeout: Maximum time to wait in milliseconds
            
        Returns:
            RenderResult with success status and archive URL if found
        """
        if not self.captcha_api_key:
            return RenderResult(
                success=False,
                error="SOLVECAPTCHA_API_KEY not configured. Set it in docker-compose.yml to use !render."
            )
        
        try:
            await self._ensure_browser()
            
            context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                # Navigate to archive.today
                await page.goto(self.ARCHIVE_URL, wait_until="networkidle", timeout=30000)
                
                # Fill in the URL
                await page.fill('input[name="url"]', url)
                
                # Click submit
                await page.click('input[type="submit"]')
                
                # Wait for navigation
                await page.wait_for_load_state("networkidle", timeout=30000)
                
                # Check for CAPTCHA and solve if needed
                captcha_solved = await self._check_and_solve_captcha(page)
                if not captcha_solved:
                    return RenderResult(
                        success=False,
                        error="Failed to solve CAPTCHA"
                    )
                
                # Wait for the archive to complete or find existing
                # archive.today redirects to the archived page when done
                start_time = asyncio.get_event_loop().time()
                while (asyncio.get_event_loop().time() - start_time) * 1000 < timeout:
                    current_url = page.url
                    
                    # Check if we're on an archived page
                    if "/wip/" in current_url:
                        # Still processing, wait
                        await asyncio.sleep(2)
                        await page.reload()
                        continue
                    elif "archive.today/" in current_url or "archive.is/" in current_url:
                        # Check if it's a valid archive URL (has a hash)
                        path = current_url.split("archive.today/")[-1].split("archive.is/")[-1]
                        if path and not path.startswith("?") and len(path) > 5:
                            return RenderResult(
                                success=True,
                                archive_url=current_url
                            )
                    
                    await asyncio.sleep(2)
                
                return RenderResult(
                    success=False,
                    error="Timeout waiting for archive to complete"
                )
                
            finally:
                await context.close()
                
        except Exception as e:
            return RenderResult(
                success=False,
                error=str(e)
            )
