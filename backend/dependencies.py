import os
from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')

from fastapi import HTTPException, Request
from gotrue.errors import AuthApiError
from supabase import Client, create_client

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")


if not url or not key:
    print(
        "WARNING: SUPABASE_URL and SUPABASE_KEY environment variables are not set. Database functionality will be disabled."
    )
    supabase: Client = None
else:
    supabase: Client = create_client(url, key)
    print(f"authClient: {supabase}")


def get_user(req: Request):
    if not supabase:
        raise HTTPException(503, "Database not configured")
    try:
        # get authorization header
        auth_header = req.headers.get("authorization")
        if not auth_header:
            raise HTTPException(401, "Missing authorization header")
        token = auth_header.split(" ")[1]
        user = supabase.auth.get_user(token).user
        print(f"user: {user}")
        if not user:
            raise HTTPException(401)
        return user.id
    except (Exception, AuthApiError) as e:
        print(e, flush=True)
        raise HTTPException(401)


def get_user_optional(req: Request):
    if not supabase:
        return None
    try:
        auth_header = req.headers.get("authorization")
        if not auth_header:
            return None
        token = auth_header.split(" ")[1]
        user = supabase.auth.get_user(token).user
        if not user:
            return None
        return user.id
    except (Exception, AuthApiError):
        return None 