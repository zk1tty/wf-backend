import os
import time
import uuid
import base64
import jwt
import json as _json

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from .dependencies import get_current_user, supabase

router = APIRouter(prefix='/auth')
public_router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Cookie upload API
# ──────────────────────────────────────────────────────────────────────────────
# GET /crypto/public-key
# POST /auth/ott
# POST /auth/storage-state
# GET /auth/storage-state
# GET /auth/storage-state/{id}
# POST /auth/storage-state/{id}/verify
# GET /auth/storage-state/{id}/debug
# ──────────────────────────────────────────────────────────────────────────────


# In-memory store to enforce single-use OTTs
_OTT_STORE = {}


@router.post("/ott", summary="Issue one-time token for cookies upload")
async def issue_one_time_token(user_id: str = Depends(get_current_user)):
    secret = os.getenv("OTT_JWT_SECRET") or os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="OTT signing key not configured")

    try:
        ttl_min = int(os.getenv("OTT_TTL_MIN", "5"))
    except ValueError:
        ttl_min = 5

    now = int(time.time())
    exp = now + ttl_min * 60
    jti = str(uuid.uuid4())

    payload = {"sub": user_id, "aud": "storage-state", "jti": jti, "iat": now, "exp": exp}
    token = jwt.encode(payload, secret, algorithm="HS256")

    # Cleanup and record
    for key, meta in list(_OTT_STORE.items()):
        if meta.get("exp", 0) <= now or meta.get("used"):
            _OTT_STORE.pop(key, None)
    _OTT_STORE[jti] = {"sub": user_id, "exp": exp, "used": False}

    return {"ott": token, "expires_in": ttl_min * 60}


@public_router.get("/crypto/public-key")
async def get_crypto_public_key():
    """Return the current public key for client-side envelope encryption.

    Response format:
    { "kid": "rsa-2025-01", "alg": "RSA-OAEP-256", "pem": "-----BEGIN PUBLIC KEY-----..." }
    """
    kid = os.getenv("COOKIE_KID", "rsa-2025-01")
    public_key_pem = os.getenv("COOKIE_PUBLIC_KEY_PEM")

    if not public_key_pem:
        raise HTTPException(status_code=503, detail="Public key not configured")

    headers = {"Cache-Control": "public, max-age=3600"}
    return JSONResponse(content={"kid": kid, "alg": "RSA-OAEP-256", "pem": public_key_pem}, headers=headers)


@router.post("/storage-state", summary="Upload encrypted cookies (storage_state)")
async def upload_storage_state(request: Request):
    # 1) Authenticate OTT
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    ott = auth_header.split(" ", 1)[1]
    secret = os.getenv("OTT_JWT_SECRET") or os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="OTT signing key not configured")

    try:
        ott_payload = jwt.decode(ott, secret, algorithms=["HS256"], options={"verify_aud": False})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="OTT expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid OTT: {e}")

    if ott_payload.get("aud") != "storage-state":
        raise HTTPException(status_code=403, detail="Invalid OTT audience")

    user_id = ott_payload.get("sub")
    jti = ott_payload.get("jti")

    global _OTT_STORE
    meta = _OTT_STORE.get(jti)
    now = int(time.time())
    if not meta or meta.get("sub") != user_id or meta.get("exp", 0) < now or meta.get("used"):
        raise HTTPException(status_code=401, detail="OTT not found or already used")
    meta["used"] = True

    # 2) Body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    required = ["ciphertext", "nonce", "wrappedKey", "kid"]
    if not all(k in body for k in required):
        raise HTTPException(status_code=400, detail="Missing required fields")

    ciphertext_b64 = body.get("ciphertext"); nonce_b64 = body.get("nonce"); wrapped_b64 = body.get("wrappedKey"); kid_req = body.get("kid")

    # 3) Decrypt
    priv_pem = os.getenv("COOKIE_PRIVATE_KEY_PEM")
    priv_path = os.getenv("COOKIE_PRIVATE_KEY_PATH")
    if not priv_pem and priv_path and os.path.exists(priv_path):
        try:
            with open(priv_path, "r") as f:
                priv_pem = f.read()
        except Exception:
            pass
    if not priv_pem:
        raise HTTPException(status_code=503, detail="Private key not configured")

    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception:
        raise HTTPException(status_code=503, detail="Cryptography library not available")

    try:
        private_key = serialization.load_pem_private_key(priv_pem.encode("utf-8"), password=None)
        wrapped_key = base64.b64decode(wrapped_b64)
        data_key = private_key.decrypt(wrapped_key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(ciphertext_b64)
        aesgcm = AESGCM(data_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        state = _json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"decrypt_failed: {e}")

    # 4) Normalize cookies
    cookies = state.get("cookies") or []
    if not isinstance(cookies, list):
        raise HTTPException(status_code=400, detail="Invalid cookies format")

    def _norm_samesite(v):
        if v is None: return None
        s = str(v).lower()
        if s == "lax": return "Lax"
        if s == "strict": return "Strict"
        if s in ("none", "no_restriction"): return "None"
        return None

    dedup = {}
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name"); value = c.get("value"); domain = c.get("domain"); path = c.get("path", "/")
        if not name or value is None or not domain:
            continue
        expires = c.get("expires")
        if expires is None and c.get("expirationDate") is not None:
            try:
                expires = int(c.get("expirationDate"))
            except Exception:
                expires = None
        item = {"name": name, "value": value, "domain": domain, "path": path, "expires": expires,
                "httpOnly": bool(c.get("httpOnly", False)), "secure": bool(c.get("secure", False)),
                "sameSite": _norm_samesite(c.get("sameSite"))}
        # Preserve CHIPS partitionKey if provided
        if isinstance(c.get("partitionKey"), dict):
            item["partitionKey"] = {k: v for k, v in c.get("partitionKey").items() if k in ("topLevelSite","hasCrossSiteAncestor","partitionKey") and v is not None}
        key = (item["domain"].lower(), item["path"], item["name"]) 
        prev = dedup.get(key)
        if not prev or (item["expires"] or 0) > (prev.get("expires") or 0):
            dedup[key] = item
    normalized_cookies = list(dedup.values())

    # 5) Persist
    if not supabase:
        return {"id": f"st_{uuid.uuid4().hex[:8]}", "user_id": user_id, "kid": kid_req, "status": "pending", "verified": {} }

    import hashlib
    rec_id = f"st_{uuid.uuid4().hex[:8]}"
    metadata = body.get("metadata") or {}
    size_bytes = len(ciphertext)
    sha256 = hashlib.sha256(ciphertext).hexdigest()

    try:
        row = {
            "id": rec_id,
            "user_id": user_id,
            "kid": kid_req,
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "metadata": {**metadata, "size_bytes": size_bytes, "sha256": sha256},
            "verified": {},
            "status": "pending",
        }
        supabase.table("cookie_uploads").insert(row).execute()

        # Auto-verify immediately
        def _has(domain_pred, name):
            for c in normalized_cookies:
                if c.get("name") == name and domain_pred(str(c.get("domain", "")).lower()):
                    return True
            return False
        checks = {
            "x": lambda: _has(lambda d: d.endswith(".x.com") or d == "x.com", "auth_token"),
            "linkedin": lambda: _has(lambda d: d.endswith(".linkedin.com") or d.endswith(".www.linkedin.com"), "li_at"),
            "instagram": lambda: _has(lambda d: d.endswith(".instagram.com") or d == "instagram.com", "sessionid"),
            "facebook": lambda: _has(lambda d: d.endswith(".facebook.com") or d == "facebook.com", "c_user") and _has(lambda d: d.endswith(".facebook.com") or d == "facebook.com", "xs"),
            "tiktok": lambda: _has(lambda d: d.endswith(".tiktok.com") or d.endswith(".www.tiktok.com"), "sessionid") or _has(lambda d: d.endswith(".tiktok.com"), "sid_tt"),
        }
        targets = (metadata.get("sites") or list(checks.keys())) if isinstance(metadata, dict) else list(checks.keys())
        verified_map = {}
        for key in targets:
            fn = checks.get(key)
            if fn:
                try:
                    verified_map[key] = bool(fn())
                except Exception:
                    verified_map[key] = False
        new_status = "verified" if verified_map and all(verified_map.values()) else "pending"

        try:
            supabase.table("cookie_uploads").update({"verified": verified_map, "status": new_status}).eq("id", rec_id).execute()
        except Exception:
            pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist: {e}")

    return {"id": rec_id, "user_id": user_id, "kid": kid_req, "status": new_status, "verified": verified_map }


@router.get("/storage-state/{record_id}", summary="Get a cookie upload record (metadata)")
async def get_storage_state_record(record_id: str, user_id: str = Depends(get_current_user)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    try:
        data = supabase.table("cookie_uploads").select("id,user_id,kid,metadata,verified,status,created_at,updated_at,size_bytes").eq("id", record_id).single().execute().data
    except Exception:
        raise HTTPException(status_code=404, detail="Record not found")
    if not data or data.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")
    return data


@router.get("/storage-state", summary="List cookie upload records for current user")
async def list_storage_state_records(status: str = None, sites: str = None, limit: int = 20, user_id: str = Depends(get_current_user)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    limit = max(1, min(limit, 100))
    query = supabase.table("cookie_uploads").select("id,user_id,kid,metadata,verified,status,created_at,updated_at,size_bytes").eq("user_id", user_id).order("created_at", desc=True).limit(limit)
    if status in ("pending", "verified", "failed"):
        query = query.eq("status", status)
    if sites:
        try:
            wanted = [s.strip() for s in sites.split(',') if s.strip()]
            if wanted:
                data = query.execute().data
                def has_site(m):
                    s = (m or {}).get("metadata", {}).get("sites")
                    return any(x in (s or []) for x in wanted)
                items = [r for r in data if has_site(r)]
                return {"items": items}
        except Exception:
            pass
    data = query.execute().data
    return {"items": data}


@router.post("/storage-state/{record_id}/verify", summary="Verify uploaded cookies and update status")
async def verify_storage_state_record(record_id: str, user_id: str = Depends(get_current_user)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    try:
        rec = supabase.table("cookie_uploads").select("id,user_id,kid,metadata,ciphertext,wrapped_key,nonce,verified,status").eq("id", record_id).single().execute().data
    except Exception:
        raise HTTPException(status_code=404, detail="Record not found")
    if not rec or rec.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")

    # Decrypt
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception:
        raise HTTPException(status_code=503, detail="Cryptography library not available")

    priv_pem = os.getenv("COOKIE_PRIVATE_KEY_PEM")
    priv_path = os.getenv("COOKIE_PRIVATE_KEY_PATH")
    if not priv_pem and priv_path and os.path.exists(priv_path):
        try:
            with open(priv_path, "r") as f:
                priv_pem = f.read()
        except Exception:
            pass
    if not priv_pem:
        raise HTTPException(status_code=503, detail="Private key not configured")

    def _b64(s):
        if isinstance(s, (bytes, bytearray)):
            return bytes(s)
        t = str(s).strip()
        if t.startswith("\\x") or t.startswith("\\X"):
            try:
                raw = bytes.fromhex(t[2:])
                try:
                    if raw and all((32 <= b <= 126) for b in raw):
                        txt = raw.decode('ascii').replace('\n','').replace('\r','').replace(' ','')
                        txt = txt.replace('-','+').replace('_','/')
                        missing = len(txt) % 4
                        if missing:
                            txt += '=' * (4-missing)
                        return base64.b64decode(txt)
                except Exception:
                    pass
                return raw
            except Exception:
                pass
        t = t.replace('\n','').replace('\r','').replace(' ','').replace('-','+').replace('_','/')
        missing = len(t) % 4
        if missing:
            t += '=' * (4-missing)
        return base64.b64decode(t)

    try:
        private_key = serialization.load_pem_private_key(priv_pem.encode("utf-8"), password=None)
        wrapped_key = _b64(rec["wrapped_key"])
        data_key = private_key.decrypt(wrapped_key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        nonce = _b64(rec["nonce"])
        ciphertext = _b64(rec["ciphertext"])
        aesgcm = AESGCM(data_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        state = _json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        try:
            supabase.table("cookie_uploads").update({"status": "failed"}).eq("id", record_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=422, detail=f"decrypt_failed: {e}")

    cookies = state.get("cookies") or []
    sites = (rec.get("metadata") or {}).get("sites") or []
    sites = [s.lower() for s in sites]

    def has(domain_pred, name):
        for c in cookies:
            if c.get("name") == name and domain_pred(str(c.get("domain", "")).lower()):
                return True
        return False

    checks = {
        "x": lambda: has(lambda d: d.endswith(".x.com") or d == "x.com", "auth_token"),
        "linkedin": lambda: has(lambda d: d.endswith(".linkedin.com") or d.endswith(".www.linkedin.com"), "li_at"),
        "instagram": lambda: has(lambda d: d.endswith(".instagram.com") or d == "instagram.com", "sessionid"),
        "facebook": lambda: has(lambda d: d.endswith(".facebook.com") or d == "facebook.com", "c_user") and has(lambda d: d.endswith(".facebook.com") or d == "facebook.com", "xs"),
        "tiktok": lambda: has(lambda d: d.endswith(".tiktok.com") or d.endswith(".www.tiktok.com"), "sessionid") or has(lambda d: d.endswith(".tiktok.com"), "sid_tt"),
    }

    verified_map = {}
    targets = sites or list(checks.keys())
    for key in targets:
        fn = checks.get(key)
        if fn:
            try:
                verified_map[key] = bool(fn())
            except Exception:
                verified_map[key] = False

    new_status = "verified" if verified_map and all(verified_map.values()) else "pending"
    try:
        supabase.table("cookie_uploads").update({"verified": verified_map, "status": new_status}).eq("id", record_id).execute()
    except Exception:
        pass
    return {"id": record_id, "status": new_status, "verified": verified_map}


@router.get("/storage-state/{record_id}/debug", summary="Debug lengths for stored blob (owner only)")
async def debug_storage_state_record(record_id: str, user_id: str = Depends(get_current_user)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    try:
        rec = supabase.table("cookie_uploads").select("id,user_id,ciphertext,wrapped_key,nonce,metadata").eq("id", record_id).single().execute().data
    except Exception:
        raise HTTPException(status_code=404, detail="Record not found")
    if not rec or rec.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")

    def lens(v):
        if isinstance(v, (bytes, bytearray)):
            return {"type": "bytes", "len": len(v)}
        if v is None:
            return {"type": "none", "len": 0}
        t = str(v)
        return {"type": "str", "len": len(t), "head": t[:64]}

    return {
        "ciphertext": lens(rec.get("ciphertext")),
        "wrapped_key": lens(rec.get("wrapped_key")),
        "nonce": lens(rec.get("nonce")),
        "sites": (rec.get("metadata") or {}).get("sites"),
    }


@router.get("/storage-state/latest", summary="Get latest verified storage state (decrypted)")
async def get_latest_storage_state(
    sites: str = None,
    user_id: str = Depends(get_current_user)
):
    """
    Get the latest verified storage state for the current user.
    
    This endpoint returns the DECRYPTED storage state (server-side only).
    Used by backend services to load saved sessions.
    
    Query params:
    - sites: Comma-separated list (e.g., "google,linkedin")
    
    Returns:
    - Decrypted storage_state dict with cookies, origins, __envMetadata
    - Metadata about the record (id, created_at, verified, etc.)
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        # Query for latest verified storage state
        query = supabase.table("cookie_uploads") \
            .select("id,user_id,kid,ciphertext,wrapped_key,nonce,metadata,verified,status,created_at") \
            .eq("user_id", user_id) \
            .eq("status", "verified") \
            .order("created_at", desc=True) \
            .limit(1)
        
        # Filter by sites if provided
        if sites:
            site_list = [s.strip().lower() for s in sites.split(',') if s.strip()]
            # Note: Supabase jsonb filtering is complex
            # For now, fetch and filter in Python
        
        result = query.execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(
                status_code=404,
                detail="No verified storage state found for user"
            )
        
        record = result.data[0]
        
        # Filter by sites if needed
        if sites:
            site_list = [s.strip().lower() for s in sites.split(',') if s.strip()]
            metadata_sites = (record.get('metadata') or {}).get('sites', [])
            if not any(s in metadata_sites for s in site_list):
                raise HTTPException(
                    status_code=404,
                    detail=f"No storage state found for sites: {sites}"
                )
        
        # Decrypt the storage state
        priv_pem = os.getenv("COOKIE_PRIVATE_KEY_PEM")
        priv_path = os.getenv("COOKIE_PRIVATE_KEY_PATH")
        
        if not priv_pem and priv_path and os.path.exists(priv_path):
            with open(priv_path, 'r') as f:
                priv_pem = f.read()
        
        if not priv_pem:
            raise HTTPException(status_code=503, detail="Private key not configured")
        
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        try:
            private_key = serialization.load_pem_private_key(priv_pem.encode("utf-8"), password=None)
            wrapped_key = base64.b64decode(record["wrapped_key"])
            data_key = private_key.decrypt(
                wrapped_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            nonce = base64.b64decode(record["nonce"])
            ciphertext = base64.b64decode(record["ciphertext"])
            
            aesgcm = AESGCM(data_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
            
            storage_state = _json.loads(plaintext.decode("utf-8"))
            
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Decryption failed: {e}")
        
        # Return decrypted state + metadata
        return {
            "storage_state": storage_state,
            "metadata": {
                "record_id": record["id"],
                "created_at": record["created_at"],
                "verified": record.get("verified", {}),
                "sites": (record.get("metadata") or {}).get("sites", [])
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load storage state: {e}")


@router.put("/storage-state/{record_id}", summary="Update existing storage state")
async def update_storage_state(
    record_id: str,
    request: Request,
    user_id: str = Depends(get_current_user)
):
    """
    Update an existing storage state record with new cookies/localStorage.
    
    This is useful for:
    - Refreshing expired cookies after re-authentication
    - Merging new session data with existing state
    
    Request body (encrypted, same format as POST /storage-state):
    {
        "ciphertext": "base64...",
        "nonce": "base64...",
        "wrappedKey": "base64...",
        "kid": "rsa-2025-01",
        "metadata": {...}
    }
    
    Returns:
    - Updated record info with new verification status
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    # 1. Verify ownership
    try:
        existing = supabase.table("cookie_uploads") \
            .select("id,user_id,kid,metadata,verified,status") \
            .eq("id", record_id) \
            .single() \
            .execute() \
            .data
    except Exception:
        raise HTTPException(status_code=404, detail="Record not found")
    
    if not existing or existing.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")
    
    # 2. Parse new encrypted state from body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    required = ["ciphertext", "nonce", "wrappedKey", "kid"]
    if not all(k in body for k in required):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    ciphertext_b64 = body.get("ciphertext")
    nonce_b64 = body.get("nonce")
    wrapped_b64 = body.get("wrappedKey")
    kid_req = body.get("kid")
    
    # 3. Decrypt to validate and verify
    priv_pem = os.getenv("COOKIE_PRIVATE_KEY_PEM")
    priv_path = os.getenv("COOKIE_PRIVATE_KEY_PATH")
    
    if not priv_pem and priv_path and os.path.exists(priv_path):
        with open(priv_path, 'r') as f:
            priv_pem = f.read()
    
    if not priv_pem:
        raise HTTPException(status_code=503, detail="Private key not configured")
    
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import hashlib
        
        private_key = serialization.load_pem_private_key(priv_pem.encode("utf-8"), password=None)
        wrapped_key = base64.b64decode(wrapped_b64)
        data_key = private_key.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(ciphertext_b64)
        
        aesgcm = AESGCM(data_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        
        state = _json.loads(plaintext.decode("utf-8"))
        
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Decryption failed: {e}")
    
    # 4. Normalize and verify cookies
    cookies = state.get("cookies") or []
    if not isinstance(cookies, list):
        raise HTTPException(status_code=400, detail="Invalid cookies format")
    
    def _norm_samesite(v):
        if v is None:
            return None
        s = str(v).lower()
        if s == "lax":
            return "Lax"
        if s == "strict":
            return "Strict"
        if s in ("none", "no_restriction"):
            return "None"
        return None
    
    # Normalize cookies (same logic as POST endpoint)
    dedup = {}
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain")
        path = c.get("path", "/")
        if not name or value is None or not domain:
            continue
        
        expires = c.get("expires")
        if expires is None and c.get("expirationDate") is not None:
            try:
                expires = int(c.get("expirationDate"))
            except Exception:
                expires = None
        
        item = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "expires": expires,
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
            "sameSite": _norm_samesite(c.get("sameSite"))
        }
        
        if isinstance(c.get("partitionKey"), dict):
            item["partitionKey"] = {
                k: v for k, v in c.get("partitionKey").items()
                if k in ("topLevelSite", "hasCrossSiteAncestor", "partitionKey") and v is not None
            }
        
        key = (item["domain"].lower(), item["path"], item["name"])
        prev = dedup.get(key)
        if not prev or (item["expires"] or 0) > (prev.get("expires") or 0):
            dedup[key] = item
    
    normalized_cookies = list(dedup.values())
    
    # Auto-verify
    def has(domain_pred, name):
        return any(
            c.get("name") == name and domain_pred(str(c.get("domain", "")).lower())
            for c in normalized_cookies
        )
    
    checks = {
        "google": lambda: has(lambda d: d.endswith(".google.com") or d == "google.com", "SID") and has(lambda d: d.endswith(".google.com") or d == "google.com", "SIDCC"),
        "linkedin": lambda: has(lambda d: d.endswith(".linkedin.com") or d.endswith(".www.linkedin.com"), "li_at"),
        "instagram": lambda: has(lambda d: d.endswith(".instagram.com") or d == "instagram.com", "sessionid"),
        "facebook": lambda: has(lambda d: d.endswith(".facebook.com") or d == "facebook.com", "c_user") and has(lambda d: d.endswith(".facebook.com") or d == "facebook.com", "xs"),
        "tiktok": lambda: has(lambda d: d.endswith(".tiktok.com") or d.endswith(".www.tiktok.com"), "sessionid") or has(lambda d: d.endswith(".tiktok.com"), "sid_tt"),
    }
    
    new_metadata = body.get("metadata") or {}
    targets = new_metadata.get("sites") or list(checks.keys())
    
    verified_map = {}
    for key in targets:
        fn = checks.get(key)
        if fn:
            try:
                verified_map[key] = bool(fn())
            except Exception:
                verified_map[key] = False
    
    new_status = "verified" if verified_map and all(verified_map.values()) else "pending"
    
    # 5. Update database record
    try:
        import hashlib
        size_bytes = len(ciphertext)
        sha256 = hashlib.sha256(ciphertext).hexdigest()
        
        # Merge metadata (preserve existing, add new)
        merged_metadata = {**(existing.get("metadata") or {}), **new_metadata}
        merged_metadata.update({"size_bytes": size_bytes, "sha256": sha256})
        
        update_data = {
            "kid": kid_req,
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "metadata": merged_metadata,
            "verified": verified_map,
            "status": new_status,
        }
        
        supabase.table("cookie_uploads").update(update_data).eq("id", record_id).execute()
        
        return {
            "id": record_id,
            "user_id": user_id,
            "status": new_status,
            "verified": verified_map,
            "updated": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update: {e}")