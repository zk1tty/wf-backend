#!/usr/bin/env python3
"""
Playwright verification script for Railway deployment

This script verifies that Playwright is properly installed and browsers are working
before starting the main application server. It's designed to fail fast if there
are any browser-related issues in the production environment.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

def test_playwright_installation():
    """Test if Playwright is properly installed"""
    print("🔍 Testing Playwright installation...")
    
    try:
        import playwright
        print("✅ Playwright imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Playwright import failed: {e}")
        return False

def test_browser_use_import():
    """Test if browser-use can be imported"""
    print("🔍 Testing browser-use import...")
    
    try:
        from browser_use import Browser
        from browser_use.browser.browser import BrowserProfile
        print("✅ browser-use imported successfully")
        return True
    except ImportError as e:
        print(f"❌ browser-use import failed: {e}")
        return False

def check_playwright_browsers():
    """Check if Playwright browsers are installed"""
    print("🔍 Checking Playwright browser installation...")
    
    # Production path for Railway deployment
    browser_paths = [
        "/root/.cache/ms-playwright/chromium-1169/chrome-linux/chrome",  # Production
        os.path.expanduser("~/.cache/ms-playwright/chromium-1169/chrome-linux/chrome"),  # Fallback
    ]
    
    found_browsers = []
    for path in browser_paths:
        if os.path.exists(path):
            found_browsers.append(path)
            print(f"✅ Found Playwright Chromium at: {path}")
    
    if not found_browsers:
        print("❌ No Playwright browsers found at expected paths")
        
        # Try to find any Playwright directory
        playwright_dirs = [
            "/root/.cache/ms-playwright",
            os.path.expanduser("~/.cache/ms-playwright"),
        ]
        
        for playwright_dir in playwright_dirs:
            if os.path.exists(playwright_dir):
                print(f"📁 Playwright directory found: {playwright_dir}")
                try:
                    contents = os.listdir(playwright_dir)
                    print(f"   Contents: {contents}")
                except Exception as e:
                    print(f"   Error listing contents: {e}")
                break
        else:
            print("❌ No Playwright directories found")
            return False
    
    return len(found_browsers) > 0

async def test_browser_creation():
    """Test creating a browser instance"""
    print("🔍 Testing browser creation...")
    
    try:
        from browser_use import Browser
        from browser_use.browser.browser import BrowserProfile
        
        # Production configuration for Railway
        profile = BrowserProfile(
            headless=True,
            disable_security=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--single-process',
                '--no-first-run',
                '--disable-extensions'
            ]
        )
        
        browser = Browser(browser_profile=profile)
        print("✅ Browser instance created successfully")
        return browser, True
        
    except Exception as e:
        print(f"❌ Browser creation failed: {e}")
        return None, False

async def test_browser_functionality(browser):
    """Test basic browser functionality"""
    print("🔍 Testing browser functionality...")
    
    try:
        # Start browser
        await browser.start()
        print("✅ Browser started successfully")
        
        # Get current page
        page = await browser.get_current_page()
        print("✅ Got current page")
        
        # Navigate to a simple page
        await page.goto("data:text/html,<html><body><h1>Playwright Test Success</h1></body></html>")
        print("✅ Navigation successful")
        
        # Get page title
        title = await page.title()
        print(f"✅ Page title retrieved: '{title}'")
        
        # Close browser
        await browser.close()
        print("✅ Browser closed successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Browser functionality test failed: {e}")
        try:
            await browser.close()
        except:
            pass
        return False

def check_environment():
    """Check Railway deployment environment"""
    print("🔍 Checking Railway environment...")
    
    env_vars = {
        'RAILWAY_ENVIRONMENT': os.getenv('RAILWAY_ENVIRONMENT'),
        'DISPLAY': os.getenv('DISPLAY'),
        'PORT': os.getenv('PORT'),
        'PYTHONUNBUFFERED': os.getenv('PYTHONUNBUFFERED'),
    }
    
    print("📋 Environment variables:")
    for key, value in env_vars.items():
        print(f"  {key}: {value}")
    
    # Check if we're in production
    is_production = env_vars['RAILWAY_ENVIRONMENT'] is not None
    print(f"🌍 Environment: {'Production' if is_production else 'Development'}")
    
    return is_production

async def main():
    """Run all Playwright verification tests"""
    print("🚀 Starting Playwright verification for Railway deployment...")
    print(f"⏰ Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Check environment first
    is_production = check_environment()
    print()
    
    # Test 1: Playwright installation
    playwright_ok = test_playwright_installation()
    print()
    
    # Test 2: browser-use import
    browser_use_ok = test_browser_use_import()
    print()
    
    # Test 3: Browser installation
    browsers_ok = check_playwright_browsers()
    print()
    
    # Test 4: Browser creation
    browser, creation_ok = await test_browser_creation()
    print()
    
    # Test 5: Browser functionality (only if creation succeeded)
    functionality_ok = False
    if creation_ok and browser:
        functionality_ok = await test_browser_functionality(browser)
        print()
    
    # Summary
    print("📋 Verification Summary:")
    print(f"  Environment: {'Production' if is_production else 'Development'}")
    print(f"  Playwright Installation: {'✅ PASS' if playwright_ok else '❌ FAIL'}")
    print(f"  browser-use Import: {'✅ PASS' if browser_use_ok else '❌ FAIL'}")
    print(f"  Browser Installation: {'✅ PASS' if browsers_ok else '❌ FAIL'}")
    print(f"  Browser Creation: {'✅ PASS' if creation_ok else '❌ FAIL'}")
    print(f"  Browser Functionality: {'✅ PASS' if functionality_ok else '❌ FAIL'}")
    
    all_passed = all([playwright_ok, browser_use_ok, browsers_ok, creation_ok, functionality_ok])
    print(f"\n🎯 Overall Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    if all_passed:
        print("\n🎉 Playwright verification successful!")
        print("🚀 Ready to start application server!")
        return True
    else:
        print("\n❌ Playwright verification failed!")
        print("\n🔧 Common fixes for Railway deployment:")
        if not playwright_ok:
            print("  - Install Playwright: pip install playwright")
        if not browsers_ok:
            print("  - Install browsers: playwright install chromium")
        if not functionality_ok:
            print("  - Install dependencies: playwright install-deps chromium")
        print("  - Check Dockerfile includes all Playwright setup steps")
        print("  - Verify xvfb is running for headless browser support")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        if not success:
            print("\n💥 Verification failed - exiting with error code")
            sys.exit(1)
        else:
            print("\n✅ Verification successful - proceeding with server startup")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n⚠️ Verification interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Verification crashed: {e}")
        sys.exit(1) 