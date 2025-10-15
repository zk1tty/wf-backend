#!/usr/bin/env python3
"""
Quick script to check what storage_state is being loaded
"""
import os
import json
import base64

print("=" * 60)
print("STORAGE STATE CHECK")
print("=" * 60)

# Check if STORAGE_STATE_JSON_B64 env var exists
if "STORAGE_STATE_JSON_B64" in os.environ:
    print("✅ STORAGE_STATE_JSON_B64 environment variable found")
    
    try:
        decoded = base64.b64decode(os.environ["STORAGE_STATE_JSON_B64"]).decode()
        data = json.loads(decoded)
        
        cookies = data.get("cookies", [])
        print(f"\n📊 Total cookies: {len(cookies)}")
        
        # Check for Google cookies
        google_cookies = [c for c in cookies if 'google.com' in c.get('domain', '')]
        print(f"📊 Google cookies: {len(google_cookies)}")
        
        # Check for critical cookies
        critical_cookies = ['SID', 'SIDCC', 'APISID', 'HSID', 'LSID', '__Host-GAPS']
        found = {}
        for name in critical_cookies:
            cookie = next((c for c in google_cookies if c.get('name') == name), None)
            if cookie:
                found[name] = {
                    'domain': cookie.get('domain'),
                    'sameSite': cookie.get('sameSite'),
                    'secure': cookie.get('secure'),
                    'httpOnly': cookie.get('httpOnly'),
                    'value_length': len(cookie.get('value', ''))
                }
            else:
                found[name] = None
        
        print("\n🔍 Critical Cookie Status:")
        for name, info in found.items():
            if info:
                print(f"  ✅ {name}: domain={info['domain']}, sameSite={info['sameSite']}, secure={info['secure']}, httpOnly={info['httpOnly']}")
            else:
                print(f"  ❌ {name}: NOT FOUND")
        
        # Check env metadata
        env_metadata = data.get('__envMetadata', {}).get('env', {})
        if env_metadata:
            print(f"\n🌐 Environment Metadata:")
            print(f"  userAgent: {env_metadata.get('userAgent', 'N/A')[:60]}...")
            print(f"  timezone: {env_metadata.get('timezone', 'N/A')}")
            print(f"  language: {env_metadata.get('language', 'N/A')}")
        else:
            print("\n⚠️  No environment metadata found")
            
    except Exception as e:
        print(f"❌ Error decoding STORAGE_STATE_JSON_B64: {e}")
else:
    print("❌ STORAGE_STATE_JSON_B64 environment variable NOT found")
    
    # Check local file
    if os.path.exists("storage_state.json"):
        print("\n📄 Local storage_state.json exists")
        try:
            with open("storage_state.json", "r") as f:
                data = json.load(f)
            cookies = data.get("cookies", [])
            google_cookies = [c for c in cookies if 'google.com' in c.get('domain', '')]
            print(f"   Total cookies in file: {len(cookies)}")
            print(f"   Google cookies in file: {len(google_cookies)}")
            
            # Check for SIDCC in file
            sidcc = next((c for c in google_cookies if c.get('name') == 'SIDCC'), None)
            if sidcc:
                print(f"   ✅ SIDCC found in local file")
            else:
                print(f"   ❌ SIDCC NOT found in local file")
        except Exception as e:
            print(f"   ❌ Error reading file: {e}")

print("\n" + "=" * 60)

