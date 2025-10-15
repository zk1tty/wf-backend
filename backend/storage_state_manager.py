"""
Storage State Manager

Manages loading and saving of browser storage state (cookies + localStorage + env metadata).
Handles multiple storage sources with clear precedence and provides encryption/persistence.

Sources (in priority order):
1. Database (Supabase) - Encrypted, user-owned, production
2. Per-user local file - Development/testing
3. Environment variable - Deployment-specific
4. Repository root file - Quick dev fallback
"""

import os
import json
import base64
import logging
import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class StorageStateManager:
    """
    Manages storage state loading and saving with multiple sources.
    
    Responsibilities:
    - Load storage state with clear precedence
    - Save storage state to appropriate target
    - Merge states intelligently
    - Validate cookie completeness
    """
    
    def __init__(self):
        """Initialize the storage state manager"""
        self.base_profile_dir = Path.home() / ".browseruse" / "profiles"
        self.base_profile_dir.mkdir(parents=True, exist_ok=True)
        
        # Locks for thread-safe saving per user
        self._save_locks: Dict[str, asyncio.Lock] = {}
        
        logger.info("StorageStateManager initialized")
    
    # ===================================================================
    # LOADING: Priority-based loading from multiple sources
    # ===================================================================
    
    async def load_storage_state_with_priority(
        self,
        user_id: Optional[str] = None,
        site_filter: Optional[str] = None,
        force_source: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load storage state with clear precedence.
        
        Priority:
        1. Database (Supabase) - if user_id provided and FEATURE_USE_COOKIES=true
        2. Per-user local file - ~/.browseruse/profiles/{user_id}/storage_state.json
        3. Environment variable - STORAGE_STATE_JSON_B64
        4. Repository root file - ./storage_state.json
        
        Args:
            user_id: User identifier for database/file lookup
            site_filter: Filter by site (e.g., 'google' for Google cookies only)
            force_source: Force specific source ('db', 'user_file', 'env', 'root_file')
            
        Returns:
            Dict with keys: 'state', 'source', 'user_id', 'verified', etc.
            None if no storage state found
        """
        sources_attempted = []
        
        # Force specific source if requested
        if force_source:
            logger.info(f"Forcing source: {force_source}")
            return await self._load_from_source(force_source, user_id, site_filter)
        
        # Priority 1: Database (requires user_id + FEATURE_USE_COOKIES)
        if user_id and os.getenv('FEATURE_USE_COOKIES', 'true').lower() == 'true':
            try:
                result = await self._load_from_database(user_id, site_filter)
                if result:
                    logger.info(f"✅ Loaded storage_state from DATABASE for user {user_id}")
                    return {
                        "state": result['state'],
                        "source": "database",
                        "user_id": user_id,
                        "record_id": result.get('record_id'),
                        "verified": result.get('verified', False)
                    }
            except Exception as e:
                logger.warning(f"Database load failed: {e}")
                sources_attempted.append("database")
        
        # Priority 2: Per-user local file
        if user_id:
            try:
                user_file = self.base_profile_dir / user_id / 'storage_state.json'
                if user_file.exists():
                    with open(user_file, 'r') as f:
                        state = json.load(f)
                    logger.info(f"✅ Loaded storage_state from USER_FILE for {user_id}")
                    return {
                        "state": state,
                        "source": "user_file",
                        "user_id": user_id,
                        "path": str(user_file)
                    }
            except Exception as e:
                logger.warning(f"User file load failed: {e}")
                sources_attempted.append("user_file")
        
        # Priority 3: Environment variable (base64)
        try:
            b64 = os.getenv('STORAGE_STATE_JSON_B64')
            if b64:
                state = json.loads(base64.b64decode(b64).decode('utf-8'))
                logger.info("✅ Loaded storage_state from ENVIRONMENT variable")
                logger.warning("⚠️  Environment variable storage state is shared across all users!")
                return {
                    "state": state,
                    "source": "environment",
                    "shared": True  # Warning: shared across users
                }
        except Exception as e:
            logger.warning(f"Environment variable load failed: {e}")
            sources_attempted.append("environment")
        
        # Priority 4: Repository root file (dev fallback)
        try:
            root_file = Path('storage_state.json')
            if root_file.exists():
                with open(root_file, 'r') as f:
                    state = json.load(f)
                logger.info("✅ Loaded storage_state from ROOT file (dev fallback)")
                logger.warning("⚠️  Root file storage state is shared across all users!")
                return {
                    "state": state,
                    "source": "root_file",
                    "shared": True  # Warning: shared across users
                }
        except Exception as e:
            logger.warning(f"Root file load failed: {e}")
            sources_attempted.append("root_file")
        
        # None found
        logger.warning(
            f"No storage_state found. Attempted: {sources_attempted}. "
            f"Starting anonymous session."
        )
        return None
    
    async def _load_from_source(
        self,
        source: str,
        user_id: Optional[str],
        site_filter: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Load from specific source (for force_source parameter)"""
        if source == 'db':
            return await self._load_from_database(user_id, site_filter)
        elif source == 'user_file' and user_id:
            user_file = self.base_profile_dir / user_id / 'storage_state.json'
            if user_file.exists():
                with open(user_file, 'r') as f:
                    return {"state": json.load(f), "source": "user_file"}
        elif source == 'env':
            b64 = os.getenv('STORAGE_STATE_JSON_B64')
            if b64:
                return {"state": json.loads(base64.b64decode(b64).decode('utf-8')), "source": "environment"}
        elif source == 'root_file':
            root_file = Path('storage_state.json')
            if root_file.exists():
                with open(root_file, 'r') as f:
                    return {"state": json.load(f), "source": "root_file"}
        return None
    
    async def _load_from_database(
        self,
        user_id: str,
        site_filter: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load latest verified storage state from Supabase database.
        
        Uses existing _get_storage_state_for_user logic from backend/service.py
        """
        try:
            from .dependencies import supabase
            
            if not supabase:
                logger.debug("Supabase not configured, skipping database load")
                return None
            
            # Query for latest verified storage state
            query = supabase.table("cookie_uploads") \
                .select("id,ciphertext,wrapped_key,nonce,metadata,verified,status,created_at") \
                .eq("user_id", user_id) \
                .eq("status", "verified") \
                .order("created_at", desc=True) \
                .limit(1)
            
            # Filter by site if provided
            if site_filter:
                # Note: This requires metadata.sites to contain the filter
                # Supabase jsonb filtering
                query = query.contains("metadata", {"sites": [site_filter]})
            
            result = query.execute()
            
            if not result.data or len(result.data) == 0:
                logger.debug(f"No verified storage state found in DB for user {user_id}")
                return None
            
            record = result.data[0]
            record_id = record['id']
            
            # Decrypt the storage state
            state = await self._decrypt_storage_state(
                record['ciphertext'],
                record['wrapped_key'],
                record['nonce']
            )
            
            if not state:
                logger.error(f"Failed to decrypt storage state {record_id}")
                return None
            
            logger.info(f"Loaded and decrypted storage state from DB: {record_id}")
            
            return {
                "state": state,
                "record_id": record_id,
                "verified": record.get('verified', {}),
                "metadata": record.get('metadata', {})
            }
            
        except Exception as e:
            logger.error(f"Database load error: {e}")
            return None
    
    async def _decrypt_storage_state(
        self,
        ciphertext_b64: str,
        wrapped_key_b64: str,
        nonce_b64: str
    ) -> Optional[Dict[str, Any]]:
        """
        Decrypt storage state using server-side private key.
        
        Reuses decryption logic from storage_state_api.py
        """
        try:
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # Get private key
            priv_pem = os.getenv("COOKIE_PRIVATE_KEY_PEM")
            priv_path = os.getenv("COOKIE_PRIVATE_KEY_PATH")
            
            if not priv_pem and priv_path and os.path.exists(priv_path):
                with open(priv_path, 'r') as f:
                    priv_pem = f.read()
            
            if not priv_pem:
                logger.error("Private key not configured for decryption")
                return None
            
            # Decode base64
            private_key = serialization.load_pem_private_key(priv_pem.encode("utf-8"), password=None)
            wrapped_key = base64.b64decode(wrapped_key_b64)
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
            
            # Decrypt with AES-GCM
            aesgcm = AESGCM(data_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
            
            state = json.loads(plaintext.decode("utf-8"))
            return state
            
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None
    
    # ===================================================================
    # SAVING: Auto-save with strategy selection
    # ===================================================================
    
    async def save_storage_state_with_strategy(
        self,
        user_id: str,
        state: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save captured state to the best available target.
        
        Strategy:
        - If FEATURE_USE_COOKIES=true + Supabase available → Database (encrypted)
        - Else → Per-user local file (plaintext, local only)
        
        Args:
            user_id: User identifier
            state: Storage state dict (cookies, origins, __envMetadata)
            metadata: Optional metadata (workflow_id, auto_saved, etc.)
            
        Returns:
            Dict with 'target', 'record_id'/'path', 'encrypted'
        """
        # Thread-safe saving per user
        if user_id not in self._save_locks:
            self._save_locks[user_id] = asyncio.Lock()
        
        async with self._save_locks[user_id]:
            # Primary target: Database (production)
            if os.getenv('FEATURE_USE_COOKIES', 'true').lower() == 'true':
                try:
                    result = await self._save_to_database(user_id, state, metadata or {})
                    if result:
                        logger.info(f"✅ Saved storage_state to DATABASE: {result['record_id']}")
                        return {
                            "target": "database",
                            "record_id": result['record_id'],
                            "encrypted": True,
                            "verified": result.get('verified', {})
                        }
                except Exception as e:
                    logger.error(f"Database save failed, falling back to local file: {e}")
            
            # Fallback target: Per-user local file (development)
            try:
                user_file = self.base_profile_dir / user_id / 'storage_state.json'
                user_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(user_file, 'w') as f:
                    json.dump(state, f, indent=2)
                
                logger.info(f"✅ Saved storage_state to USER_FILE: {user_file}")
                return {
                    "target": "user_file",
                    "path": str(user_file),
                    "encrypted": False
                }
            except Exception as e:
                logger.error(f"User file save failed: {e}")
                raise RuntimeError(f"Failed to save storage state to any target: {e}")
    
    async def _save_to_database(
        self,
        user_id: str,
        state: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Encrypt and save storage state to Supabase.
        
        Reuses encryption logic from storage_state_api.py
        """
        try:
            from .dependencies import supabase
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import secrets
            import hashlib
            import uuid
            
            if not supabase:
                logger.debug("Supabase not configured")
                return None
            
            # Get public key for encryption
            public_key_pem = os.getenv("COOKIE_PUBLIC_KEY_PEM")
            if not public_key_pem:
                logger.error("Public key not configured for encryption")
                return None
            
            # Encrypt storage state
            # 1. Generate random AES key
            data_key = secrets.token_bytes(32)  # 256-bit AES key
            
            # 2. Encrypt data with AES-GCM
            plaintext = json.dumps(state).encode('utf-8')
            nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
            aesgcm = AESGCM(data_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
            
            # 3. Wrap AES key with RSA public key
            public_key = serialization.load_pem_public_key(public_key_pem.encode('utf-8'))
            wrapped_key = public_key.encrypt(
                data_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # 4. Prepare record
            record_id = f"st_{uuid.uuid4().hex[:8]}"
            kid = os.getenv("COOKIE_KID", "rsa-2025-01")
            
            size_bytes = len(ciphertext)
            sha256 = hashlib.sha256(ciphertext).hexdigest()
            
            # 5. Auto-verify cookies
            cookies = state.get('cookies', [])
            verified_map = self._verify_cookies(cookies, metadata.get('sites', []))
            
            new_status = "verified" if verified_map and all(verified_map.values()) else "pending"
            
            # 6. Insert into database
            row = {
                "id": record_id,
                "user_id": user_id,
                "kid": kid,
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "metadata": {**metadata, "size_bytes": size_bytes, "sha256": sha256},
                "verified": verified_map,
                "status": new_status,
            }
            
            supabase.table("cookie_uploads").insert(row).execute()
            
            logger.info(f"Saved encrypted storage state to DB: {record_id} (status: {new_status})")
            
            return {
                "record_id": record_id,
                "verified": verified_map,
                "status": new_status
            }
            
        except Exception as e:
            logger.error(f"Database save error: {e}")
            return None
    
    def _verify_cookies(self, cookies: List[Dict], sites: List[str]) -> Dict[str, bool]:
        """
        Verify critical cookies are present for specified sites.
        
        Reuses verification logic from storage_state_api.py
        """
        def has_cookie(domain_pred, name):
            return any(
                c.get('name') == name and domain_pred(str(c.get('domain', '')).lower())
                for c in cookies
            )
        
        checks = {
            "google": lambda: has_cookie(
                lambda d: d.endswith('.google.com') or d == 'google.com',
                'SID'
            ) and has_cookie(
                lambda d: d.endswith('.google.com') or d == 'google.com',
                'SIDCC'
            ),
            "linkedin": lambda: has_cookie(
                lambda d: d.endswith('.linkedin.com') or d.endswith('.www.linkedin.com'),
                'li_at'
            ),
            "instagram": lambda: has_cookie(
                lambda d: d.endswith('.instagram.com') or d == 'instagram.com',
                'sessionid'
            ),
            "facebook": lambda: has_cookie(
                lambda d: d.endswith('.facebook.com') or d == 'facebook.com',
                'c_user'
            ) and has_cookie(
                lambda d: d.endswith('.facebook.com') or d == 'facebook.com',
                'xs'
            ),
            "tiktok": lambda: has_cookie(
                lambda d: d.endswith('.tiktok.com') or d.endswith('.www.tiktok.com'),
                'sessionid'
            ) or has_cookie(
                lambda d: d.endswith('.tiktok.com'),
                'sid_tt'
            ),
        }
        
        # If no sites specified, check all
        targets = sites if sites else list(checks.keys())
        
        verified_map = {}
        for key in targets:
            fn = checks.get(key)
            if fn:
                try:
                    verified_map[key] = bool(fn())
                except Exception:
                    verified_map[key] = False
        
        return verified_map
    
    # ===================================================================
    # UTILITY: Helper methods
    # ===================================================================
    
    def filter_expired_cookies(self, cookies: List[Dict]) -> List[Dict]:
        """Remove already-expired cookies"""
        now = time.time()
        
        valid_cookies = []
        expired_count = 0
        
        for cookie in cookies:
            expires = cookie.get('expires', -1)
            if expires == -1 or expires > now:
                valid_cookies.append(cookie)
            else:
                expired_count += 1
        
        if expired_count > 0:
            logger.info(f"Filtered out {expired_count} expired cookies")
        
        return valid_cookies
    
    def validate_google_cookie_completeness(self, cookies: List[Dict]) -> Dict[str, bool]:
        """Check if critical Google cookies are present"""
        
        def has_cookie(domain_check, name):
            return any(
                c['name'] == name and domain_check(c.get('domain', ''))
                for c in cookies
            )
        
        checks = {
            'google_apex': has_cookie(
                lambda d: d.endswith('.google.com'),
                'SID'
            ) and has_cookie(
                lambda d: d.endswith('.google.com'),
                'SIDCC'
            ),
            'google_accounts': has_cookie(
                lambda d: d == 'accounts.google.com',
                '__Host-GAPS'
            ),
            'google_docs': has_cookie(
                lambda d: d.endswith('.docs.google.com'),
                'OSID'
            )
        }
        
        return checks


# Global instance for easy access
storage_state_manager = StorageStateManager()

