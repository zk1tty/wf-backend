import os
import logging
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

# Set up logger
logger = logging.getLogger(__name__)

# Environment variables
SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
JWT_SECRET: Optional[str] = os.getenv("SUPABASE_JWT_SECRET")

# Debug: Show environment variable status at startup
def prompt_for_missing_env_vars():
    """Prompt user to set missing environment variables interactively"""
    global SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, JWT_SECRET
    
    if not SUPABASE_URL or SUPABASE_URL == 'your_supabase_url_here':
        logger.error("SUPABASE_URL is not configured.")
        set_url = input("Would you like to set SUPABASE_URL now? (y/n): ")
        if set_url.lower() == 'y':
            SUPABASE_URL = input("Enter your SUPABASE_URL (e.g., https://your-project.supabase.co): ")
            os.environ['SUPABASE_URL'] = SUPABASE_URL
    
    if not SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_ROLE_KEY == 'your_service_role_key_here':
        logger.error("SUPABASE_SERVICE_ROLE_KEY is not configured.")
        set_key = input("Would you like to set SUPABASE_SERVICE_ROLE_KEY now? (y/n): ")
        if set_key.lower() == 'y':
            SUPABASE_SERVICE_ROLE_KEY = input("Enter your SUPABASE_SERVICE_ROLE_KEY: ")
            os.environ['SUPABASE_SERVICE_ROLE_KEY'] = SUPABASE_SERVICE_ROLE_KEY
    
    if not JWT_SECRET or JWT_SECRET == 'your_jwt_secret_here':
        logger.error("SUPABASE_JWT_SECRET is not configured.")
        set_secret = input("Would you like to set SUPABASE_JWT_SECRET now? (y/n): ")
        if set_secret.lower() == 'y':
            JWT_SECRET = input("Enter your SUPABASE_JWT_SECRET: ")
            os.environ['SUPABASE_JWT_SECRET'] = JWT_SECRET

logger.debug("=== SUPABASE ENV VARIABLES ===")
logger.debug(f"SUPABASE_URL: {'✅ SET' if SUPABASE_URL else '❌ NOT SET OR PLACEHOLDER'}")
logger.debug(f"SUPABASE_SERVICE_ROLE_KEY: {'✅ SET' if SUPABASE_SERVICE_ROLE_KEY else '❌ NOT SET OR PLACEHOLDER'}")
logger.debug(f"SUPABASE_JWT_SECRET: {'✅ SET' if JWT_SECRET else '❌ NOT SET OR PLACEHOLDER'}")
logger.debug("=============================================")

# Prompt for missing environment variables if running interactively
if os.getenv('INTERACTIVE_MODE', 'true').lower() == 'true':
    missing_vars = []
    if not SUPABASE_URL or SUPABASE_URL == 'your_supabase_url_here':
        missing_vars.append('SUPABASE_URL')
    if not SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_ROLE_KEY == 'your_service_role_key_here':
        missing_vars.append('SUPABASE_SERVICE_ROLE_KEY')  
    if not JWT_SECRET or JWT_SECRET == 'your_jwt_secret_here':
        missing_vars.append('SUPABASE_JWT_SECRET')
    
    if missing_vars:
        logger.warning(f"Missing Supabase configuration: {', '.join(missing_vars)}")
        prompt_missing = input("Would you like to configure these now? (y/n): ")
        if prompt_missing.lower() == 'y':
            prompt_for_missing_env_vars()

# Initialize Supabase client
supabase: Optional[Client] = None

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    logger.warning(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not properly configured. Database functionality will be disabled."
    )
else:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        supabase = None

if not JWT_SECRET:
    logger.warning("SUPABASE_JWT_SECRET is not properly configured. JWT verification will be disabled.")


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