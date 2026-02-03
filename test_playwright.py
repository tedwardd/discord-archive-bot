#!/usr/bin/env python3
"""Test script to debug Playwright connection to archive.today"""

import asyncio
from playwright.async_api import async_playwright


async def test_archive_today():
    print("Starting Playwright test...")
    
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        print("Creating context...")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        print("Creating page...")
        page = await context.new_page()
        
        # Test 1: Basic navigation
        print("\n--- Test 1: Navigate to archive.today ---")
        try:
            response = await page.goto("https://archive.today", wait_until="domcontentloaded", timeout=30000)
            print(f"Status: {response.status}")
            print(f"URL: {page.url}")
            print("SUCCESS: Page loaded")
        except Exception as e:
            print(f"FAILED: {e}")
        
        # Test 2: Wait for networkidle
        print("\n--- Test 2: Wait for networkidle ---")
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
            print("SUCCESS: networkidle reached")
        except Exception as e:
            print(f"FAILED: {e}")
        
        # Test 3: Check for form
        print("\n--- Test 3: Check for URL input form ---")
        try:
            input_field = await page.query_selector('input[name="url"]')
            if input_field:
                print("SUCCESS: Found URL input field")
            else:
                print("FAILED: URL input field not found")
                # Print page content for debugging
                content = await page.content()
                print(f"Page content (first 1000 chars): {content[:1000]}")
        except Exception as e:
            print(f"FAILED: {e}")
        
        # Test 4: Check for CAPTCHA
        print("\n--- Test 4: Check for CAPTCHA elements ---")
        try:
            # Check for reCAPTCHA
            recaptcha = await page.query_selector(".g-recaptcha")
            if recaptcha:
                print("Found reCAPTCHA element (.g-recaptcha)")
                sitekey = await recaptcha.get_attribute("data-sitekey")
                if sitekey:
                    print(f"  reCAPTCHA sitekey: {sitekey}")
            
            # Check for reCAPTCHA iframe
            recaptcha_iframe = await page.query_selector("iframe[src*='recaptcha']")
            if recaptcha_iframe:
                print("Found reCAPTCHA iframe")
            
            # Check for hCaptcha
            hcaptcha = await page.query_selector(".h-captcha, [data-hcaptcha-sitekey]")
            if hcaptcha:
                print("Found hCaptcha element")
                sitekey = await hcaptcha.get_attribute("data-sitekey") or await hcaptcha.get_attribute("data-hcaptcha-sitekey")
                if sitekey:
                    print(f"  hCaptcha sitekey: {sitekey}")
            
            # Check for hCaptcha iframe
            hcaptcha_iframe = await page.query_selector("iframe[src*='hcaptcha']")
            if hcaptcha_iframe:
                print("Found hCaptcha iframe")
            
            # Generic sitekey check
            sitekey_element = await page.query_selector("[data-sitekey]")
            if sitekey_element:
                key = await sitekey_element.get_attribute("data-sitekey")
                print(f"Found generic data-sitekey: {key}")
            
            if not recaptcha and not recaptcha_iframe and not hcaptcha and not hcaptcha_iframe and not sitekey_element:
                print("No CAPTCHA elements found on page")
        except Exception as e:
            print(f"FAILED: {e}")
        
        # Test 5: Try filling and submitting
        print("\n--- Test 5: Fill form and submit ---")
        try:
            test_url = "https://example.com"
            await page.fill('input[name="url"]', test_url)
            print(f"Filled URL: {test_url}")
            
            await page.click('input[type="submit"]')
            print("Clicked submit")
            
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            print(f"After submit URL: {page.url}")
            
            # Check for CAPTCHA now
            recaptcha = await page.query_selector(".g-recaptcha, iframe[src*='recaptcha']")
            hcaptcha = await page.query_selector(".h-captcha, iframe[src*='hcaptcha']")
            sitekey = await page.query_selector("[data-sitekey]")
            
            if recaptcha:
                print("reCAPTCHA appeared after submit")
            if hcaptcha:
                print("hCaptcha appeared after submit")
            if sitekey:
                key = await sitekey.get_attribute("data-sitekey")
                print(f"Sitekey: {key}")
            if not recaptcha and not hcaptcha and not sitekey:
                print("No CAPTCHA after submit")
                
        except Exception as e:
            print(f"FAILED: {e}")
        
        # Take screenshot (save to /data which is mounted as a volume)
        print("\n--- Taking screenshot ---")
        try:
            await page.screenshot(path="/data/archive_today_test.png")
            print("Screenshot saved to /data/archive_today_test.png (./data/ on host)")
        except Exception as e:
            print(f"Screenshot failed: {e}")
        
        await context.close()
        await browser.close()
        print("\nTest complete.")


if __name__ == "__main__":
    asyncio.run(test_archive_today())
