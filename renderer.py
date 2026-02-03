import os
import re
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
            # Save debug screenshot
            await page.screenshot(path="/data/captcha_check.png")
            print(f"Debug screenshot saved to /data/captcha_check.png")
            print(f"Current URL: {page.url}")
            
            # Get page title to check for CAPTCHA page
            title = await page.title()
            print(f"Page title: {title}")
            
            # Check page content for CAPTCHA indicators
            content = await page.content()
            has_recaptcha_script = "recaptcha" in content.lower()
            has_hcaptcha_script = "hcaptcha" in content.lower()
            has_one_more_step = "one more step" in content.lower()
            print(f"Page contains: recaptcha={has_recaptcha_script}, hcaptcha={has_hcaptcha_script}, 'one more step'={has_one_more_step}")
            
            site_key = None
            
            # Method 1: Extract sitekey from page HTML using regex (most reliable)
            sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', content)
            if sitekey_match:
                site_key = sitekey_match.group(1)
                print(f"Found sitekey via regex: {site_key}")
            
            # Method 2: Check for reCAPTCHA element
            if not site_key:
                recaptcha_element = await page.query_selector(".g-recaptcha")
                if recaptcha_element:
                    site_key = await recaptcha_element.get_attribute("data-sitekey")
                    print(f"Found .g-recaptcha element with sitekey: {site_key}")
            
            # Method 3: Check any element with data-sitekey
            if not site_key:
                sitekey_element = await page.query_selector("[data-sitekey]")
                if sitekey_element:
                    site_key = await sitekey_element.get_attribute("data-sitekey")
                    print(f"Found [data-sitekey] element with sitekey: {site_key}")
            
            # Method 4: Look in iframe src for sitekey
            if not site_key:
                iframe = await page.query_selector("iframe[src*='recaptcha']")
                if iframe:
                    src = await iframe.get_attribute("src")
                    if src:
                        k_match = re.search(r'[?&]k=([^&]+)', src)
                        if k_match:
                            site_key = k_match.group(1)
                            print(f"Found sitekey in iframe src: {site_key}")
            
            if site_key:
                print(f"Solving reCAPTCHA with sitekey: {site_key}")
                
                solution = await self._solve_captcha(page, site_key, 'recaptcha')
                if solution:
                    print(f"Got solution, injecting...")
                    # Inject the solution
                    await page.evaluate(f"""
                        var response = '{solution}';
                        // Try various ways to set the response
                        var el1 = document.querySelector('#g-recaptcha-response');
                        if (el1) el1.value = response;
                        
                        var el2 = document.querySelector('textarea[name="g-recaptcha-response"]');
                        if (el2) el2.value = response;
                        
                        var el3 = document.querySelector('[name="g-recaptcha-response"]');
                        if (el3) el3.value = response;
                        
                        // Try to trigger callback if exists
                        if (typeof ___grecaptcha_cfg !== 'undefined') {{
                            var clients = ___grecaptcha_cfg.clients;
                            for (var key in clients) {{
                                if (clients[key].callback) {{
                                    clients[key].callback(response);
                                }}
                            }}
                        }}
                    """)
                    
                    # Find and click submit button
                    submit_btn = await page.query_selector('input[type="submit"], button[type="submit"], button')
                    if submit_btn:
                        print("Clicking submit button...")
                        await submit_btn.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=60000)
                        await page.screenshot(path="/data/after_captcha_submit.png")
                        print("Screenshot after submit saved to /data/after_captcha_submit.png")
                    return True
                else:
                    print("Failed to solve reCAPTCHA - no solution returned")
                    return False
            
            # Check for hCaptcha
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
                        submit_btn = await page.query_selector('input[type="submit"], button[type="submit"], button')
                        if submit_btn:
                            await submit_btn.click()
                            await page.wait_for_load_state("domcontentloaded", timeout=60000)
                        return True
                    else:
                        print("Failed to solve hCaptcha")
                        return False
            
            # Check if we're on a CAPTCHA page but couldn't find elements
            if has_one_more_step or has_recaptcha_script:
                print("WARNING: Appears to be CAPTCHA page but couldn't find sitekey element")
                # Print all elements with data-sitekey for debugging
                all_sitekeys = await page.query_selector_all("[data-sitekey]")
                print(f"Found {len(all_sitekeys)} elements with data-sitekey attribute")
                
                # Try waiting a bit for reCAPTCHA to fully load
                print("Waiting 3 seconds for reCAPTCHA to load...")
                await asyncio.sleep(3)
                await page.screenshot(path="/data/captcha_after_wait.png")
                
                # Try regex again after waiting
                content = await page.content()
                sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', content)
                if sitekey_match:
                    site_key = sitekey_match.group(1)
                    print(f"Found sitekey after wait: {site_key}")
                    
                    solution = await self._solve_captcha(page, site_key, 'recaptcha')
                    if solution:
                        await page.evaluate(f"""
                            var response = '{solution}';
                            var el = document.querySelector('#g-recaptcha-response') || 
                                     document.querySelector('textarea[name="g-recaptcha-response"]') ||
                                     document.querySelector('[name="g-recaptcha-response"]');
                            if (el) el.value = response;
                        """)
                        
                        submit_btn = await page.query_selector('input[type="submit"], button[type="submit"], button')
                        if submit_btn:
                            await submit_btn.click()
                            await page.wait_for_load_state("domcontentloaded", timeout=60000)
                        return True
                
                return False
            
            print("No CAPTCHA found on page")
            return True
            
        except Exception as e:
            print(f"CAPTCHA check error: {e}")
            import traceback
            traceback.print_exc()
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
                print(f"Navigating to {self.ARCHIVE_URL}...")
                await page.goto(self.ARCHIVE_URL, wait_until="domcontentloaded", timeout=60000)
                print(f"Page loaded. URL: {page.url}")
                
                # Save initial screenshot
                await page.screenshot(path="/data/render_initial.png")
                print("Initial screenshot saved to /data/render_initial.png")
                
                # Check for CAPTCHA on initial page load
                print("Checking for initial CAPTCHA...")
                captcha_solved = await self._check_and_solve_captcha(page)
                if not captcha_solved:
                    await page.screenshot(path="/data/render_captcha_failed.png")
                    return RenderResult(
                        success=False,
                        error="Failed to solve initial CAPTCHA. Check /data/render_captcha_failed.png"
                    )
                
                # Now look for the URL input form
                url_input = await page.query_selector('input[name="url"]')
                if not url_input:
                    return RenderResult(
                        success=False,
                        error="Could not find URL input form after CAPTCHA"
                    )
                
                # Fill in the URL
                print(f"Filling URL: {url}")
                await page.fill('input[name="url"]', url)
                
                # Click submit
                print("Clicking submit button...")
                await page.click('input[type="submit"]')
                
                # Wait for navigation (60s timeout)
                print("Waiting for page load after submit...")
                await page.wait_for_load_state("domcontentloaded", timeout=60000)
                
                # Save screenshot after form submission
                await page.screenshot(path="/data/render_after_submit.png")
                print(f"After submit screenshot saved. Current URL: {page.url}")
                
                # Check for another CAPTCHA after submit
                print("Checking for CAPTCHA after submit...")
                captcha_solved = await self._check_and_solve_captcha(page)
                if not captcha_solved:
                    await page.screenshot(path="/data/render_post_captcha_failed.png")
                    return RenderResult(
                        success=False,
                        error="Failed to solve CAPTCHA after submit. Check /data/render_post_captcha_failed.png"
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
                    elif "archive.today/" in current_url or "archive.is/" in current_url or "archive.ph/" in current_url:
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
