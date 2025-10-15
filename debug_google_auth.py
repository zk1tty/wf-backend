#!/usr/bin/env python3
"""
Debug Google Authentication Issues
Checks cookie state before and after navigation to identify why Google treats browser as signed-out
"""
import os
import json
import base64
import asyncio
import time
from workflow_use.browser.browser_factory import BrowserFactory
from playwright.async_api import Page

async def debug_google_auth():
    """Debug why Google authentication is failing"""
    
    # Load storage state
    storage_state_data = None
    if "STORAGE_STATE_JSON_B64" in os.environ:
        try:
            storage_state_data = json.loads(base64.b64decode(os.environ["STORAGE_STATE_JSON_B64"]).decode())
        except Exception as e:
            print(f"Error decoding STORAGE_STATE_JSON_B64: {e}")
    elif os.path.exists("storage_state.json"):
        try:
            with open("storage_state.json", "r") as f:
                storage_state_data = json.load(f)
        except Exception as e:
            print(f"Error loading storage_state.json: {e}")
    
    if not storage_state_data:
        print("No storage state found. Exiting.")
        return 1
    
    print("🔍 Starting Google Authentication Debug")
    print("=" * 50)
    
    bf = BrowserFactory()
    browser, _ = await bf.create_browser_with_rrweb(
        mode="headless",
        session_id="google-debug",
        headless=True,
        storage_state=storage_state_data
    )
    page = await browser.get_current_page()
    
    # Function to get all cookies via CDP
    async def get_all_cookies():
        cdp = await page.context.new_cdp_session(page)
        cookies = (await cdp.send("Network.getAllCookies"))["cookies"]
        await cdp.detach()
        return cookies
    
    # Function to analyze cookies by domain
    def analyze_cookies(cookies, domain_filter=None):
        current_time = time.time()
        result = {}
        
        for cookie in cookies:
            domain = cookie.get("domain", "")
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            expires = cookie.get("expires", 0)
            secure = cookie.get("secure", False)
            httpOnly = cookie.get("httpOnly", False)
            sameSite = cookie.get("sameSite", "None")
            
            if domain_filter and domain_filter not in domain:
                continue
                
            if domain not in result:
                result[domain] = []
            
            # Check if cookie is expired or about to expire
            is_expired = expires > 0 and expires <= current_time
            expires_soon = expires > 0 and expires <= (current_time + 300)  # 5 minutes
            
            result[domain].append({
                "name": name,
                "value_length": len(value),
                "has_value": bool(value),
                "expires": expires,
                "expires_human": time.ctime(expires) if expires > 0 else "Session",
                "is_expired": is_expired,
                "expires_soon": expires_soon,
                "secure": secure,
                "httpOnly": httpOnly,
                "sameSite": sameSite
            })
        
        return result
    
    print("\n📋 INITIAL COOKIE STATE (After Browser Creation)")
    print("-" * 50)
    
    initial_cookies = await get_all_cookies()
    google_cookies = analyze_cookies(initial_cookies)
    
    # Focus on Google domains
    for domain in [".google.com", "accounts.google.com", "docs.google.com"]:
        if domain in google_cookies:
            print(f"\n{domain}:")
            for cookie in google_cookies[domain]:
                status = "❌ EXPIRED" if cookie["is_expired"] else ("⚠️ EXPIRES SOON" if cookie["expires_soon"] else "✅ VALID")
                print(f"  {cookie['name']}: {status} (expires: {cookie['expires_human']})")
                print(f"    secure={cookie['secure']}, httpOnly={cookie['httpOnly']}, sameSite={cookie['sameSite']}")
    
    print("\n🌐 NAVIGATION TEST 1: Google.com")
    print("-" * 50)
    
    try:
        await page.goto("https://www.google.com/?hl=en")
        await asyncio.sleep(2)
        
        post_google_cookies = await get_all_cookies()
        google_analysis = analyze_cookies(post_google_cookies, "google.com")
        
        print("Cookies after google.com navigation:")
        for domain, cookies in google_analysis.items():
            print(f"\n{domain}:")
            for cookie in cookies:
                print(f"  {cookie['name']}: {'✅' if cookie['has_value'] else '❌'}")
        
        # Check for session cookies
        apex_cookies = [c for c in post_google_cookies if c.get("domain") in [".google.com", "google.com", "www.google.com"]]
        session_cookies = ["SID", "SIDCC", "APISID", "HSID"]
        found_sessions = {name: any(c.get("name") == name for c in apex_cookies) for name in session_cookies}
        
        print(f"\nSession cookies minted: {found_sessions}")
        
    except Exception as e:
        print(f"Navigation to google.com failed: {e}")
    
    print("\n🔐 NAVIGATION TEST 2: Accounts.google.com")
    print("-" * 50)
    
    try:
        await page.goto("https://accounts.google.com/CheckCookie?continue=https%3A%2F%2Fmyaccount.google.com%2F")
        await asyncio.sleep(3)
        
        current_url = await page.evaluate("window.location.href")
        print(f"Final URL after CheckCookie: {current_url}")
        
        # Check if we got redirected to sign-in
        if "signin" in current_url.lower() or "accounts.google.com/signin" in current_url:
            print("❌ REDIRECTED TO SIGN-IN - Google doesn't recognize the session")
        elif "myaccount.google.com" in current_url:
            print("✅ SUCCESSFULLY AUTHENTICATED - Reached MyAccount")
        elif "support" in current_url or "clear" in current_url:
            print("⚠️ CLEAR CACHE REDIRECT - Session cookies are invalid")
        else:
            print(f"🤔 UNEXPECTED REDIRECT: {current_url}")
        
        post_accounts_cookies = await get_all_cookies()
        accounts_analysis = analyze_cookies(post_accounts_cookies, "accounts.google.com")
        
        print("\naccounts.google.com cookies after navigation:")
        for domain, cookies in accounts_analysis.items():
            print(f"\n{domain}:")
            for cookie in cookies:
                status = "❌ EXPIRED" if cookie["is_expired"] else ("⚠️ EXPIRES SOON" if cookie["expires_soon"] else "✅ VALID")
                print(f"  {cookie['name']}: {status}")
        
    except Exception as e:
        print(f"Navigation to accounts.google.com failed: {e}")
    
    print("\n📊 SUMMARY & RECOMMENDATIONS")
    print("=" * 50)
    
    final_cookies = await get_all_cookies()
    
    # Check for critical missing cookies
    missing_critical = []
    critical_cookies = {
        ".google.com": ["SID", "HSID", "APISID"],
        "accounts.google.com": ["LSID", "__Host-GAPS"]
    }
    
    for domain, required in critical_cookies.items():
        domain_cookies = [c.get("name") for c in final_cookies if domain in c.get("domain", "")]
        missing = [name for name in required if name not in domain_cookies]
        if missing:
            missing_critical.append(f"{domain}: {missing}")
    
    if missing_critical:
        print("❌ MISSING CRITICAL COOKIES:")
        for missing in missing_critical:
            print(f"  - {missing}")
        print("\n💡 RECOMMENDATIONS:")
        print("  1. Check if source cookies are expired or invalid")
        print("  2. Verify cookie attributes match Google's requirements")
        print("  3. Consider doing a fresh in-cloud login")
    else:
        print("✅ All critical cookies present")
        print("\n💡 If still signed-out, check:")
        print("  1. Cookie expiry times")
        print("  2. SameSite attribute values")
        print("  3. Secure flag requirements")
    
    await browser.close()
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(debug_google_auth())
    exit(exit_code)
