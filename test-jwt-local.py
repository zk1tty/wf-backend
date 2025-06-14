#!/usr/bin/env python3
"""
Test JWT token verification using the same logic as the backend
"""
import os
import jwt
from dotenv import load_dotenv
from pathlib import Path

# Load .env file from the project root (same as backend)
root_dir = Path(__file__).parent
env_path = root_dir / '.env'
load_dotenv(dotenv_path=env_path)

# Get JWT secret (same as backend)
JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

print("🔍 JWT Token Verification Test")
print("=" * 50)
print(f"JWT_SECRET loaded: {'✅ YES' if JWT_SECRET else '❌ NO'}")
if JWT_SECRET:
    print(f"JWT_SECRET (first 20 chars): {JWT_SECRET[:20]}...")

# Test token from Chrome extension
test_token = "eyJhbGciOiJIUzI1NiIsImtpZCI6IklKclRKS29xc0Z6ZmxUVWMiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL2RtZ3Rzc2VxcXNpeXV1emhkeG5uLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJiOTNkOGNhMy01YTFjLTQ2ZDMtOTU3MS0zNmFkNDRkMDlkNmQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzQ5ODk0NjU2LCJpYXQiOjE3NDk4OTEwNTYsImVtYWlsIjoibm9yaWthQDB4Y2VyYmVydXMuaW8iLCJwaG9uZSI6IiIsImFwcF9tZXRhZGF0YSI6eyJwcm92aWRlciI6Imdvb2dsZSIsInByb3ZpZGVycyI6WyJnb29nbGUiXX0sInVzZXJfbWV0YWRhdGEiOnsiYXZhdGFyX3VybCI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hL0FDZzhvY0xpOXlmMTRLSVBTUXl0RWV1eXhTdWZadTN5TEtXS3FjS3JGT0FoNm5aNVZCdzB5alk9czk2LWMiLCJjdXN0b21fY2xhaW1zIjp7ImhkIjoiMHhjZXJiZXJ1cy5pbyJ9LCJlbWFpbCI6Im5vcmlrYUAweGNlcmJlcnVzLmlvIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImZ1bGxfbmFtZSI6Ik5vcmlrYSBLaXphd2EiLCJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJuYW1lIjoiTm9yaWthIEtpemF3YSIsInBob25lX3ZlcmlmaWVkIjpmYWxzZSwicGljdHVyZSI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hL0FDZzhvY0xpOXlmMTRLSVBTUXl0RWV1eXhTdWZadTN5TEtXS3FjS3JGT0FoNm5aNVZCdzB5alk9czk2LWMiLCJwcm92aWRlcl9pZCI6IjExMTQwNDkzNjAzNzQ3MDU4MjQ2MSIsInN1YiI6IjExMTQwNDkzNjAzNzQ3MDU4MjQ2MSJ9LCJyb2xlIjoiYXV0aGVudGljYXRlZCIsImFhbCI6ImFhbDEiLCJhbXIiOlt7Im1ldGhvZCI6Im9hdXRoIiwidGltZXN0YW1wIjoxNzQ5ODkxMDU2fV0sInNlc3Npb25faWQiOiI3NzU4OTkzOC1jZGZkLTQ3MTMtODU0NS03YjY0OTkyY2M1ZTMiLCJpc19hbm9ueW1vdXMiOmZhbHNlfQ.52YDdHL7OkKYW5PD9t6laai_yhZ3OC27Qml7IQFTexs"

print(f"\n🎯 Testing token (first 50 chars): {test_token[:50]}...")

if not JWT_SECRET:
    print("❌ Cannot test - JWT_SECRET not available")
    exit(1)

try:
    # Decode without verification first to see the payload
    print("\n📋 Token payload (unverified):")
    unverified = jwt.decode(test_token, options={"verify_signature": False})
    print(f"  - User: {unverified.get('email', 'N/A')}")
    print(f"  - Sub: {unverified.get('sub', 'N/A')}")
    print(f"  - Aud: {unverified.get('aud', 'N/A')}")
    print(f"  - Iss: {unverified.get('iss', 'N/A')}")
    print(f"  - Exp: {unverified.get('exp', 'N/A')}")
    print(f"  - Iat: {unverified.get('iat', 'N/A')}")
    
    # Check expiration
    import time
    now = int(time.time())
    exp = unverified.get('exp', 0)
    is_expired = exp < now
    print(f"  - Expired: {'❌ YES' if is_expired else '✅ NO'}")
    if is_expired:
        print(f"  - Expired {(now - exp) // 60} minutes ago")
    else:
        print(f"  - Expires in {(exp - now) // 60} minutes")
    
    # Try different verification approaches
    print("\n🔐 Verification attempts:")
    
    # 1. Try with audience validation disabled (like backend might be doing)
    try:
        print("1️⃣ Trying without audience validation...")
        payload = jwt.decode(test_token, JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
        print("✅ SUCCESS! Token signature is valid (no aud check)")
        print(f"✅ User authenticated: {payload.get('email')}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # 2. Try with explicit audience
    try:
        print("2️⃣ Trying with 'authenticated' audience...")
        payload = jwt.decode(test_token, JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        print("✅ SUCCESS! Token signature is valid (with aud)")
        print(f"✅ User authenticated: {payload.get('email')}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # 3. Try the exact same way as backend (no audience specified)
    try:
        print("3️⃣ Trying exact backend method (HS256 only)...")
        payload = jwt.decode(test_token, JWT_SECRET, algorithms=["HS256"])
        print("✅ SUCCESS! Token signature is valid (backend method)")
        print(f"✅ User authenticated: {payload.get('email')}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        
except Exception as e:
    print(f"❌ FAILED: Unexpected error - {e}")

print("\n" + "=" * 50) 