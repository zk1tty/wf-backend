import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the project root
root_dir = Path(__file__).parent.parent
env_path = root_dir / '.env'
load_dotenv(dotenv_path=env_path)

from fastapi import Depends, HTTPException, Request, status
import jwt
from supabase import Client, create_client
from typing import Optional, Dict, Any

# Environment variables
SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
JWT_SECRET: Optional[str] = os.getenv("SUPABASE_JWT_SECRET")

# Initialize Supabase client
supabase: Optional[Client] = None

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print(
        "WARNING: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are not set. Database functionality will be disabled."
    )
else:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    print(f"Supabase client initialized: {supabase}")

if not JWT_SECRET:
    print("WARNING: SUPABASE_JWT_SECRET is not set. JWT verification will be disabled.")


def get_current_user(req: Request) -> Dict[str, Any]:
    """
    Verify Supabase JWT token and return user payload.
    Raises HTTPException if authentication fails.
    """
    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not configured"
        )
    
    auth_header = req.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )
    
    token = auth_header.split(" ", 1)[1]
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


def get_current_user_optional(req: Request) -> Optional[Dict[str, Any]]:
    """
    Verify Supabase JWT token and return user payload if valid.
    Returns None if authentication fails or is missing.
    """
    if not JWT_SECRET:
        return None
    
    try:
        auth_header = req.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ", 1)[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except (jwt.PyJWTError, IndexError):
        return None


# Legacy functions for backward compatibility (deprecated)
def get_user(req: Request) -> str:
    """
    Legacy function - returns user ID from JWT payload.
    Use get_current_user() for new code.
    """
    payload = get_current_user(req)
    return payload.get("sub", "")


def get_user_optional(req: Request) -> Optional[str]:
    """
    Legacy function - returns user ID from JWT payload if valid.
    Use get_current_user_optional() for new code.
    """
    payload = get_current_user_optional(req)
    return payload.get("sub") if payload else None 