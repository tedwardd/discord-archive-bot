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
    
    def _solve_recaptcha_sync(self, site_key: str, page_url: str) -> str | None:
        """
        Synchronous reCAPTCHA solver using SolveCaptcha.
        Called in executor to avoid blocking.
        """
        try:
            from solvecaptcha import SolveCaptcha
            
            solver = SolveCaptcha(self.captcha_api_key)
            result = solver.recaptcha(
                sitekey=site_key,
                url=page_url
            )
            return result.get('code')
        except Exception as e:
            print(f"SolveCaptcha error: {e}")
            return None
    
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
    
    async def _solve_captcha(self, page: Page, site_key: str, captcha_type: str, timeout: int = 120) -> str | None:
        """
        Solve CAPTCHA using SolveCaptcha service.
        Returns the solution token or None if failed.
        
        Args:
            page: The Playwright page
            site_key: The CAPTCHA sitekey
            captcha_type: Either 'recaptcha' or 'hcaptcha'
            timeout: Maximum seconds to wait for solution (default 120)
        """
        if not self.captcha_api_key:
            return None
        
        solver_func = self._solve_recaptcha_sync if captcha_type == 'recaptcha' else self._solve_hcaptcha_sync
        
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    solver_func,
                    site_key,
                    page.url
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print(f"CAPTCHA solving timed out after {timeout} seconds")
            return None
    
    async def _check_and_solve_captcha(self, page: Page) -> bool:
        """
        Check for CAPTCHA on page and attempt to solve it.
        Returns True if no CAPTCHA or successfully solved.
        """
        try:
            # Check for reCAPTCHA
            recaptcha_element = await page.query_selector(".g-recaptcha, [data-sitekey]")
            if recaptcha_element:
                site_key = await recaptcha_element.get_attribute("data-sitekey")
                if site_key:
                    print(f"Found reCAPTCHA with sitekey: {site_key}")
                    
                    solution = await self._solve_captcha(page, site_key, 'recaptcha')
                    if solution:
                        # Inject the solution
                        await page.evaluate(f"""
                            document.querySelector('#g-recaptcha-response').value = '{solution}';
                            // Also try textarea version
                            var ta = document.querySelector('textarea[name="g-recaptcha-response"]');
                            if (ta) ta.value = '{solution}';
                        """)
                        
                        # Find and click submit button
                        submit_btn = await page.query_selector('input[type="submit"], button[type="submit"]')
                        if submit_btn:
                            await submit_btn.click()
                            await page.wait_for_load_state("networkidle", timeout=60000)
                        return True
                    else:
                        print("Failed to solve reCAPTCHA")
                        return False
            
            # Check for hCaptcha iframe
            hcaptcha_element = await page.query_selector("[data-hcaptcha-sitekey], .h-captcha")
            if hcaptcha_element:
                site_key = await hcaptcha_element.get_attribute("data-sitekey") or await hcaptcha_element.get_attribute("data-hcaptcha-sitekey")
                if site_key:
                    print(f"Found hCaptcha with sitekey: {site_key}")
                    
                    solution = await self._solve_captcha(page, site_key, 'hcaptcha')
                    if solution:
                        # Inject the solution
                        await page.evaluate(f"""
                            document.querySelector('[name="h-captcha-response"]').value = '{solution}';
                            document.querySelector('[name="g-recaptcha-response"]').value = '{solution}';
                        """)
                        
                        # Submit the form
                        submit_btn = await page.query_selector('input[type="submit"], button[type="submit"]')
                        if submit_btn:
                            await submit_btn.click()
                            await page.wait_for_load_state("networkidle", timeout=60000)
                        return True
                    else:
                        print("Failed to solve hCaptcha")
                        return False
            
            print("No CAPTCHA found on page")
            return True
            
        except Exception as e:
            print(f"CAPTCHA check error: {e}")
            return False
    
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
                # Navigate to archive.today (60s timeout - site can be slow)
                await page.goto(self.ARCHIVE_URL, wait_until="domcontentloaded", timeout=60000)
                
                # Check for CAPTCHA on initial page load
                print("Checking for initial CAPTCHA...")
                captcha_solved = await self._check_and_solve_captcha(page)
                if not captcha_solved:
                    return RenderResult(
                        success=False,
                        error="Failed to solve initial CAPTCHA"
                    )
                
                # Now look for the URL input form
                url_input = await page.query_selector('input[name="url"]')
                if not url_input:
                    return RenderResult(
                        success=False,
                        error="Could not find URL input form after CAPTCHA"
                    )
                
                # Fill in the URL
                await page.fill('input[name="url"]', url)
                
                # Click submit
                await page.click('input[type="submit"]')
                
                # Wait for navigation (60s timeout)
                await page.wait_for_load_state("domcontentloaded", timeout=60000)
                
                # Check for another CAPTCHA after submit
                captcha_solved = await self._check_and_solve_captcha(page)
                if not captcha_solved:
                    return RenderResult(
                        success=False,
                        error="Failed to solve CAPTCHA after submit"
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
