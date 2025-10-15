#!/usr/bin/env python3
"""
Test script to verify Patchright setup and browser functionality
"""
import asyncio
import os
import sys
from pathlib import Path

# Add the project root to Python path for robust imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_patchright_installation():
    """Test if Patchright is properly installed"""
    print("🔍 Testing Patchright installation...")
    
    try:
        import patchright
        # Try to get version, but don't fail if not available
        try:
            import pkg_resources
            version = pkg_resources.get_distribution("patchright").version
            print(f"✅ Patchright imported successfully - version: {version}")
        except Exception:
            print("✅ Patchright imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Patchright import failed: {e}")
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

def check_patchright_browsers():
    """Check if Patchright browsers are installed"""
    print("🔍 Checking Patchright browser installation...")
    
    # Common Patchright browser paths (same as Playwright)
    browser_paths = [
        "/root/.cache/ms-playwright/chromium-1169/chrome-linux/chrome",  # Production
        os.path.expanduser("~/.cache/ms-playwright/chromium-1169/chrome-linux/chrome"),  # Local Linux
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-1169/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),  # macOS
    ]
    
    found_browsers = []
    for path in browser_paths:
        if os.path.exists(path):
            found_browsers.append(path)
            print(f"✅ Found Patchright Chromium at: {path}")
    
    if not found_browsers:
        print("⚠️  No Patchright browsers found at common paths")
        
        # Try to find any Playwright directory (Patchright uses same paths)
        playwright_dirs = [
            "/root/.cache/ms-playwright",
            os.path.expanduser("~/.cache/ms-playwright"),
            os.path.expanduser("~/Library/Caches/ms-playwright"),
        ]
        
        for playwright_dir in playwright_dirs:
            if os.path.exists(playwright_dir):
                print(f"📁 Patchright directory found: {playwright_dir}")
                try:
                    contents = os.listdir(playwright_dir)
                    print(f"   Contents: {contents}")
                except Exception as e:
                    print(f"   Error listing contents: {e}")
                break
        else:
            print("❌ No Patchright directories found")
            return False
    
    return len(found_browsers) > 0

async def test_browser_creation():
    """Test creating a browser instance"""
    print("🔍 Testing browser creation...")
    
    try:
        from browser_use import Browser
        from browser_use.browser.browser import BrowserProfile
        
        # Test with headless profile (similar to production)
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
        await page.goto("data:text/html,<html><body><h1>Patchright Test Success</h1></body></html>")
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

async def main():
    """Run all Patchright tests"""
    print("🚀 Starting Patchright setup verification...\n")
    
    # Test 1: Patchright installation
    patchright_ok = test_patchright_installation()
    print()
    
    # Test 2: browser-use import
    browser_use_ok = test_browser_use_import()
    print()
    
    # Test 3: Browser installation
    browsers_ok = check_patchright_browsers()
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
    print("📋 Test Summary:")
    print(f"  Patchright Installation: {'✅ PASS' if patchright_ok else '❌ FAIL'}")
    print(f"  browser-use Import: {'✅ PASS' if browser_use_ok else '❌ FAIL'}")
    print(f"  Browser Installation: {'✅ PASS' if browsers_ok else '❌ FAIL'}")
    print(f"  Browser Creation: {'✅ PASS' if creation_ok else '❌ FAIL'}")
    print(f"  Browser Functionality: {'✅ PASS' if functionality_ok else '❌ FAIL'}")
    
    all_passed = all([patchright_ok, browser_use_ok, browsers_ok, creation_ok, functionality_ok])
    print(f"\n🎯 Overall Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    if all_passed:
        print("\n🎉 Patchright setup is working correctly!")
        print("🚀 Ready for production deployment!")
    else:
        print("\n⚠️  Some tests failed. Common fixes:")
        if not patchright_ok:
            print("  - Install Patchright: pip install patchright")
        if not browsers_ok:
            print("  - Install browsers: patchright install chromium")
        if not functionality_ok:
            print("  - Check system dependencies: patchright install-deps chromium")
        print("  - For production: ensure Dockerfile includes all Patchright setup steps")

if __name__ == "__main__":
    asyncio.run(main()) 