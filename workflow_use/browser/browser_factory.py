#!/usr/bin/env python3
"""
BrowserFactory: Browser lifecycle management

This class provides clean browser creation and management, replacing the scattered
browser creation patterns throughout the codebase.

Key responsibilities:
- Create workflow browsers using WorkflowService._create_browser_instance()
- Start browsers and verify they're ready
- Create browser + rrweb recorder combinations (atomic operation)
- Browser cleanup and resource management

What it DOESN'T do:
- rrweb injection or management (delegated to RRWebRecorder)
- Visual streaming setup (delegated to RRWebStreamersManager)
- Workflow execution (stays in WorkflowService)
"""

import asyncio
import logging
import os
import shutil
import tempfile
import sys
from typing import Optional, Tuple, Callable, Dict, Any, List

# CRITICAL: Monkey-patch to use Patchright instead of Playwright
# This must happen BEFORE importing browser_use
import patchright.async_api
import playwright.async_api
# Replace playwright's async_playwright with patchright's version
playwright.async_api.async_playwright = patchright.async_api.async_playwright
logger_init = logging.getLogger(__name__)
logger_init.info("🔧 Monkey-patched playwright.async_api.async_playwright to use patchright")

from browser_use import Browser
from browser_use.browser import BrowserProfile
from patchright.async_api import Page
from urllib.parse import urlparse

from .profile_manager import profile_manager
from .custom_screensaver import show_custom_dvd_screensaver
from ..rrweb.recorder import RRWebRecorder

logger = logging.getLogger(__name__)


class BrowserFactory:
    """
    Factory for creating browsers with optional rrweb recording.
    
    Single Responsibility: Browser lifecycle management and atomic creation.
    Does NOT handle recording details - that's RRWebRecorder's job.
    """
    
    def __init__(self):
        """Initialize the browser factory."""
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        logger.info("BrowserFactory initialized")
        # Track cookie logging state per session to avoid noisy duplicates
        self._cookie_log_state: Dict[str, Dict[str, bool]] = {}
    
    async def create_browser_with_rrweb(
        self, 
        mode: str, 
        session_id: str, 
        event_callback: Optional[Callable] = None,
        user_id: Optional[str] = None,
        headless: bool = True,
        storage_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Browser, RRWebRecorder]:
        """
        Create a browser with rrweb recording capability.
        
        This method creates a complete browser+recorder setup atomically.
        If any step fails, the entire operation fails fast.
        
        Args:
            mode: Browser mode (e.g., 'visual', 'headless')
            session_id: Unique session identifier
            event_callback: Callback function for rrweb events
            user_id: Optional user identifier for profile management
            headless: Whether to run browser in headless mode
            
        Returns:
            Tuple of (Browser, RRWebRecorder) ready for use
            
        Raises:
            RuntimeError: If browser creation or recorder setup fails
        """
        logger.info(f"Creating browser with rrweb for session {session_id} (mode: {mode})")
        
        try:
            # Critical: Pre-launch Clean-up
            # Extra hardening: proactively remove any lingering Chromium singleton locks for this session
            try:
                from .profile_manager import profile_manager as _pm
                session_dir = _pm.get_session_dir(session_id)
                # Kill any lingering Chromium processes referencing this session dir (pre-launch hardening)
                try:
                    killed = _pm.kill_chromium_processes_for_dir(session_dir)
                    if killed:
                        logger.info(f"Killed {killed} Chromium processes for session {session_id} pre-launch")
                except Exception:
                    pass
                # Remove lock artifacts
                _pm._remove_chromium_singleton_locks(session_dir)
            except Exception:
                pass

            # Prepare env context overrides from storage_state metadata (if provided)
            context_overrides: Dict[str, Any] = {}
            try:
                if storage_state and isinstance(storage_state, dict) and storage_state.get("__envMetadata"):
                    env = (storage_state.get("__envMetadata") or {}).get("env") or {}
                    # Accept-Language from languages list
                    languages = env.get("languages") or []
                    accept_lang = None
                    if isinstance(languages, list) and languages:
                        parts = []
                        for idx, lang in enumerate(languages[:4]):
                            if idx == 0:
                                parts.append(str(lang))
                            else:
                                q = max(0.1, 1.0 - 0.1 * idx)
                                parts.append(f"{lang};q={q:.1f}")
                        accept_lang = ",".join(parts)
                    # Map env -> Playwright context options
                    user_agent = env.get("userAgent")
                    if user_agent:
                        context_overrides["user_agent"] = user_agent
                    locale = env.get("language") or env.get("locale")
                    if locale:
                        context_overrides["locale"] = locale
                    tz = env.get("timezone") or env.get("timezoneId")
                    if tz:
                        context_overrides["timezone_id"] = tz
                    viewport = env.get("viewport") or {}
                    if isinstance(viewport, dict):
                        w = viewport.get("width"); h = viewport.get("height")
                        if isinstance(w, int) and isinstance(h, int):
                            context_overrides["viewport"] = {"width": w, "height": h}
                    dpr = env.get("devicePixelRatio") or env.get("deviceScaleFactor")
                    if isinstance(dpr, (int, float)):
                        context_overrides["device_scale_factor"] = float(dpr)
                    if accept_lang:
                        context_overrides["extra_http_headers"] = {"Accept-Language": accept_lang}
            except Exception as _e:
                logger.warning(f"Failed to derive env overrides for session {session_id}: {_e}")

            # Step 1: Create browser instance (with fallback if profile is locked/EAGAIN)
            browser, temp_profile_dir = await self._create_browser_instance(
                session_id=session_id,
                user_id=user_id,
                headless=headless,
                context_overrides=context_overrides or None
            )
            
            # Step 2: Get the browser page
            page = await self._get_browser_page(browser, session_id)

            # Step 2.25: Log env overrides application (applied at context creation time)
            try:
                if context_overrides:
                    logger.info(f"Applied env metadata at context creation for session {session_id}: {list(context_overrides.keys())}")
            except Exception:
                pass

            # Step 2.5: Apply storage state (cookies + localStorage init) if provided
            if storage_state:
                try:
                    # Log what we're about to apply
                    num_cookies = len(storage_state.get('cookies', []))
                    num_origins = len(storage_state.get('origins', []))
                    google_cookies = sum(1 for c in storage_state.get('cookies', []) if 'google.com' in c.get('domain', ''))
                    
                    # Get metadata if available
                    env_meta = storage_state.get('__envMetadata', {}).get('env', {})
                    user_agent = env_meta.get('userAgent', 'N/A')[:60] + '...' if env_meta.get('userAgent') else 'N/A'
                    timezone = env_meta.get('timezone', 'N/A')
                    
                    logger.info(
                        f"📦 Applying storage state for session {session_id}:\n"
                        f"   ├─ Cookies: {num_cookies} total ({google_cookies} Google)\n"
                        f"   ├─ LocalStorage: {num_origins} origins\n"
                        f"   ├─ User-Agent: {user_agent}\n"
                        f"   └─ Timezone: {timezone}"
                    )
                    
                    await self._apply_storage_state(page, storage_state, session_id)
                    logger.info(f"✅ Successfully applied storage state for session {session_id}")
                except Exception as e:
                    logger.warning(f"❌ Failed to apply storage state for session {session_id}: {e}")
            
            # Step 3: Show screensaver (for visual modes)
            if mode == 'visual':
                await self._setup_screensaver(page, session_id)
            
            # Step 4: Create RRWebRecorder
            recorder = RRWebRecorder(
                session_id=session_id,
                page=page,
                event_callback=event_callback
            )
            
            # Step 5: Attach recorder to browser for controller access
            browser._rrweb_recorder = recorder
            logger.debug(f"Attached _rrweb_recorder to browser for session {session_id}")
            
            # Step 6: Store session information
            self._active_sessions[session_id] = {
                'browser': browser,
                'recorder': recorder,
                'mode': mode,
                'created_at': asyncio.get_event_loop().time(),
                # Track any temporary fallback profile for cleanup
                'temp_profile_dir': temp_profile_dir,
            }
            
            # Install optional cookie verification logger for Google flows
            try:
                await self._install_google_cookie_logger(page, session_id)
            except Exception as _e:
                logger.debug(f"Cookie logger setup skipped: {_e}")

            logger.info(f"✅ Browser+Recorder created successfully for session {session_id}")
            return browser, recorder
            
        except Exception as e:
            logger.error(f"❌ Failed to create browser with rrweb for session {session_id}: {e}")
            # Clean up any partial state
            await self._cleanup_failed_creation(session_id)
            raise RuntimeError(f"Browser creation failed for session {session_id}: {e}")

    async def _apply_storage_state(self, page: Page, storage_state: Dict[str, Any], session_id: str) -> None:
        """Apply cookies and localStorage-like values to the current context/page.

        Notes:
        - Use storage_state.json
        - Cookies are applied directly to the context.
        - localStorage values are applied via an init script that sets items when the
          page origin matches.
        """
        # Apply cookies
        cookies: List[Dict[str, Any]] = []
        for c in storage_state.get('cookies', []):
            try:
                cookie: Dict[str, Any] = {
                    'name': c['name'],
                    'value': c['value'],
                    'domain': c.get('domain', ''),
                    'path': c.get('path', '/'),
                    'expires': c.get('expires', 0),
                    'httpOnly': c.get('httpOnly', False),
                    'secure': c.get('secure', True),
                }
                # sameSite is optional; include only if present and valid
                if 'sameSite' in c and c['sameSite'] in ['Lax', 'Strict', 'None']:
                    cookie['sameSite'] = c['sameSite']
                # Preserve partitionKey for CHIPS fidelity if provided
                if isinstance(c.get('partitionKey'), dict):
                    cookie['partitionKey'] = c['partitionKey']
                cookies.append(cookie)
            except KeyError:
                continue

        if cookies:
            # Log Google cookie count before applying
            google_cookies = [c for c in cookies if 'google.com' in c.get('domain', '')]
            logger.info(f"[CookieApply] Applying {len(cookies)} total cookies, {len(google_cookies)} for Google domains to session {session_id}")
            
            # Log specific critical cookies with expiry info
            critical = ['SID', 'SIDCC', 'APISID', 'HSID', 'LSID', '__Host-GAPS', 'OSID']
            found_critical = {}
            for name in critical:
                cookie = next((c for c in google_cookies if c['name'] == name), None)
                if cookie:
                    import time
                    expires = cookie.get('expires', -1)
                    if expires > 0:
                        days_until_expiry = (expires - time.time()) / 86400
                        found_critical[name] = f"✓ (expires in {days_until_expiry:.1f} days)"
                    else:
                        found_critical[name] = "✓ (session)"
                else:
                    found_critical[name] = "✗"
            
            logger.info(f"[CookieApply] Critical Google cookies status: {found_critical}")
            
            # Try a different approach: set cookies after initial navigation to avoid Google's anti-bot detection
            logger.info(f"[CookieDebug] Deferring cookie application to avoid anti-bot detection")
            
            # Store cookies for later application
            if not hasattr(self, '_pending_cookies'):
                self._pending_cookies = {}
            self._pending_cookies[session_id] = cookies
            
            # Also try immediate application as fallback
            try:
                await page.context.add_cookies(cookies)
                logger.info(f"[CookieDebug] Applied {len(cookies)} cookies immediately as fallback")
            except Exception as e:
                logger.warning(f"[CookieDebug] Immediate cookie application failed: {e}")

        # Prepare localStorage init mapping
        origin_to_kv: Dict[str, Dict[str, str]] = {}
        for origin_entry in storage_state.get('origins', []):
            origin = origin_entry.get('origin')
            kv_list = origin_entry.get('localStorage', []) or []
            if origin and isinstance(kv_list, list) and kv_list:
                origin_to_kv[origin] = {item.get('name'): item.get('value') for item in kv_list if 'name' in item and 'value' in item}

        if origin_to_kv:
            # Log localStorage being injected
            total_items = sum(len(items) for items in origin_to_kv.values())
            logger.info(f"[LocalStorageApply] Injecting localStorage for {len(origin_to_kv)} origins ({total_items} items total)")
            for origin, items in origin_to_kv.items():
                logger.info(f"[LocalStorageApply]   └─ {origin}: {len(items)} items")
            
            # Inject an init script that sets localStorage for matching origin as early as possible
            import json as _json
            mapping_json = _json.dumps(origin_to_kv)
            script = f"""
                (() => {{
                    try {{
                        const mapping = {mapping_json};
                        const ls = mapping[location.origin];
                        if (!ls) return;
                        for (const [k, v] of Object.entries(ls)) {{
                            try {{ localStorage.setItem(k, String(v)); }} catch {{}}
                        }}
                    }} catch {{}}
                }})();
            """
            await page.context.add_init_script(script=script)
    
    async def create_browser_only(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        headless: bool = True
    ) -> Browser:
        """
        Create a browser without rrweb recording.
        
        Args:
            session_id: Unique session identifier  
            user_id: Optional user identifier for profile management
            headless: Whether to run browser in headless mode
            
        Returns:
            Browser instance ready for use
            
        Raises:
            RuntimeError: If browser creation fails
        """
        logger.info(f"Creating browser-only for session {session_id}")
        
        try:
            # Create browser instance
            browser, temp_profile_dir = await self._create_browser_instance(
                session_id=session_id,
                user_id=user_id,
                headless=headless
            )
            
            # Store session information (no recorder)
            self._active_sessions[session_id] = {
                'browser': browser,
                'recorder': None,
                'mode': 'browser_only',
                'created_at': asyncio.get_event_loop().time(),
                'temp_profile_dir': temp_profile_dir,
            }
            
            logger.info(f"✅ Browser-only created successfully for session {session_id}")
            return browser
            
        except Exception as e:
            logger.error(f"❌ Failed to create browser-only for session {session_id}: {e}")
            await self._cleanup_failed_creation(session_id)
            raise RuntimeError(f"Browser creation failed for session {session_id}: {e}")
    
    async def cleanup_session(self, session_id: str) -> bool:
        """
        Clean up a session and its resources.
        
        Args:
            session_id: Session to clean up
            
        Returns:
            True if cleanup was successful, False otherwise
        """
        if session_id not in self._active_sessions:
            logger.warning(f"Session {session_id} not found for cleanup")
            return False
        
        logger.info(f"Cleaning up session {session_id}")
        
        try:
            session_info = self._active_sessions[session_id]
            
            # Stop recorder if present
            recorder = session_info.get('recorder')
            if recorder:
                await recorder.stop_recording()
                logger.debug(f"Recorder stopped for session {session_id}")
            
            # Close browser
            browser = session_info.get('browser')
            if browser:
                await browser.close()
                logger.debug(f"Browser closed for session {session_id}")
            
            # Clean up any temporary fallback profile created by retry logic
            temp_profile_dir = session_info.get('temp_profile_dir')
            if temp_profile_dir and isinstance(temp_profile_dir, str):
                try:
                    shutil.rmtree(temp_profile_dir, ignore_errors=True)
                    logger.debug(f"Removed temporary profile directory: {temp_profile_dir}")
                except Exception:
                    pass

            # Clean up profile and remove any Chromium singleton locks
            profile_manager.cleanup_session(session_id)
            logger.debug(f"Profile cleaned up for session {session_id}")
            
            # Remove from active sessions
            del self._active_sessions[session_id]
            
            logger.info(f"✅ Session {session_id} cleaned up successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")
            # Remove from active sessions even if cleanup had issues
            self._active_sessions.pop(session_id, None)
            return False
    
    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get information about an active session"""
        session_info = self._active_sessions.get(session_id)
        if not session_info:
            return None
        
        return {
            'session_id': session_id,
            'mode': session_info['mode'],
            'created_at': session_info['created_at'],
            'has_recorder': session_info['recorder'] is not None,
            'browser_active': session_info['browser'] is not None
        }
    
    def list_active_sessions(self) -> List[str]:
        """Get list of active session IDs"""
        return list(self._active_sessions.keys())
    
    async def get_browser_for_session(self, session_id: str) -> Optional[Browser]:
        """Get browser instance for a session"""
        session_info = self._active_sessions.get(session_id)
        return session_info.get('browser') if session_info else None
    
    async def get_recorder_for_session(self, session_id: str) -> Optional[RRWebRecorder]:
        """Get recorder instance for a session"""
        session_info = self._active_sessions.get(session_id)
        return session_info.get('recorder') if session_info else None
    
    async def extract_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Extract current browser state (cookies + localStorage + env metadata).
        
        This captures the complete state needed to resume a session later:
        - All cookies from the browser context
        - localStorage for current page origin
        - Environment metadata (user agent, timezone, viewport, etc.)
        
        Args:
            session_id: Session to extract state from
            
        Returns:
            Dict with keys: 'cookies', 'origins', '__envMetadata'
            None if session not found or extraction fails
        """
        session_info = self._active_sessions.get(session_id)
        if not session_info:
            logger.warning(f"Session {session_id} not found for state extraction")
            return None
        
        try:
            browser = session_info.get('browser')
            if not browser:
                logger.error(f"Browser not available for session {session_id}")
                return None
            
            page = await browser.get_current_page()
            if not page:
                logger.error(f"Page not available for session {session_id}")
                return None
            
            # 1. Extract cookies via Playwright context
            # Note: Per test results, this does NOT capture partitionKey,
            # but Google doesn't use CHIPS partitioning, so this is sufficient
            cookies = await page.context.cookies()
            logger.info(f"Extracted {len(cookies)} cookies from session {session_id}")
            
            # 2. Extract localStorage for current origin
            # Note: This only captures localStorage from the current page's origin
            # Multi-origin capture would require navigating to each domain
            origins_data = await page.evaluate("""
                () => {
                    const origins = [];
                    
                    // Current frame
                    try {
                        const origin = window.location.origin;
                        const localStorage = [];
                        for (let i = 0; i < window.localStorage.length; i++) {
                            const key = window.localStorage.key(i);
                            localStorage.push({
                                name: key,
                                value: window.localStorage.getItem(key)
                            });
                        }
                        if (localStorage.length > 0) {
                            origins.push({origin, localStorage});
                        }
                    } catch (e) {
                        console.error('Failed to extract localStorage:', e);
                    }
                    
                    return origins;
                }
            """)
            
            if origins_data and len(origins_data) > 0:
                logger.info(
                    f"Extracted localStorage from {len(origins_data)} origins "
                    f"({sum(len(o.get('localStorage', [])) for o in origins_data)} items)"
                )
            
            # 3. Extract environment metadata
            # This helps preserve browser fingerprint across sessions
            env_metadata = await page.evaluate("""
                () => ({
                    userAgent: navigator.userAgent,
                    language: navigator.language,
                    languages: navigator.languages,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    viewport: {
                        width: window.innerWidth,
                        height: window.innerHeight
                    },
                    devicePixelRatio: window.devicePixelRatio
                })
            """)
            
            logger.info(f"Extracted environment metadata for session {session_id}")
            
            # 4. Assemble complete state
            state = {
                "cookies": cookies,
                "origins": origins_data,
                "__envMetadata": {"env": env_metadata}
            }
            
            # Log summary
            google_cookies = sum(1 for c in cookies if 'google.com' in c.get('domain', ''))
            logger.info(
                f"✅ Successfully extracted session state: "
                f"{len(cookies)} cookies ({google_cookies} Google), "
                f"{len(origins_data)} origins with localStorage"
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Failed to extract session state for {session_id}: {e}")
            return None
    
    # ===================================================================
    # PRIVATE METHODS: Browser Creation Steps
    # ===================================================================
    
    async def _create_browser_instance(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        headless: bool = True,
        context_overrides: Optional[Dict[str, Any]] = None
    ) -> Tuple[Browser, Optional[str]]:
        """
        Create the actual browser instance with profile.
        
        Raises:
            RuntimeError: If browser creation fails
        """
        try:
            # Get browser profile configuration
            config = profile_manager.create_browser_profile_config(
                session_id=session_id,
                user_id=user_id
            )
            
            # Override with method parameters
            config.update({
                'headless': headless
            })
            
            logger.debug(f"Using profile config for session {session_id}")
            
            # Create browser with profile
            # If context_overrides are provided, pass them through to BrowserProfile
            # These map to Playwright's new_context options in browser-use
            if context_overrides:
                config.update(context_overrides)
            profile = BrowserProfile(**config)
            browser = Browser(browser_profile=profile)
            
            # Start the browser
            await browser.start()
            logger.debug(f"Browser instance created and started for session {session_id}")
            # No temp profile was needed
            return browser, None
            
        except Exception as e:
            # First attempt failed; check if it's a lock/resource error and retry with a fresh temp profile
            err_text = str(e)
            logger.warning(f"Primary browser start failed for session {session_id}: {err_text}")

            # Post-failure cleanup: kill lingering processes and remove locks for the session dir
            try:
                session_dir = profile_manager.get_session_dir(session_id)
                try:
                    killed = profile_manager.kill_chromium_processes_for_dir(session_dir)
                    if killed:
                        logger.info(f"Killed {killed} Chromium processes for session {session_id} after failed start")
                except Exception:
                    pass
                profile_manager._remove_chromium_singleton_locks(session_dir)
            except Exception:
                pass

            should_retry = False
            try:
                import errno as _errno
                # EAGAIN (11) indicates resource temporarily unavailable
                if getattr(e, 'errno', None) in (_errno.EAGAIN, 11):
                    should_retry = True
            except Exception:
                pass

            lock_indicators = [
                'Resource temporarily unavailable',
                'Profile at',
                'is locked',
                'Chrome subprocess failed to start',
                'timeout',
            ]
            if any(s in err_text for s in lock_indicators):
                should_retry = True

            if not should_retry:
                logger.error(f"Failed to create browser instance for session {session_id}: {e}")
                raise RuntimeError(f"Browser instance creation failed: {e}")

            # Retry path: create a fresh temporary user_data_dir to bypass lock
            temp_profile_dir = tempfile.mkdtemp(prefix="browseruse-tmp-singleton-")
            logger.warning(
                f"Retrying browser start for session {session_id} with temporary profile: {temp_profile_dir}"
            )

            try:
                # Refresh config and override user_data_dir
                retry_config = dict(config)
                retry_config['user_data_dir'] = temp_profile_dir
                # Preserve key stability flags; ensure headless parameter stays as requested
                retry_config['headless'] = headless

                retry_profile = BrowserProfile(**retry_config)
                retry_browser = Browser(browser_profile=retry_profile)
                await retry_browser.start()
                logger.info(
                    f"Browser started successfully on retry with temporary profile for session {session_id}"
                )
                return retry_browser, temp_profile_dir
            except Exception as retry_err:
                # Cleanup temp dir if retry also failed
                try:
                    shutil.rmtree(temp_profile_dir, ignore_errors=True)
                except Exception:
                    pass
                logger.error(
                    f"Retry with temporary profile failed for session {session_id}: {retry_err}"
                )
                raise RuntimeError(
                    f"Browser instance creation failed (including retry with fresh temp profile). "
                    f"Original error: {err_text}. Retry error: {retry_err}"
                )
    
    async def _get_browser_page(self, browser: Browser, session_id: str) -> Page:
        """
        Get the main page from the browser.
        
        Raises:
            RuntimeError: If page retrieval fails
        """
        try:
            # Get the browser's page
            page = await browser.get_current_page()
            if not page:
                raise RuntimeError("Browser page not available")
            
            logger.debug(f"Browser page retrieved for session {session_id}")
            return page
            
        except Exception as e:
            logger.error(f"Failed to get browser page for session {session_id}: {e}")
            raise RuntimeError(f"Page retrieval failed: {e}")

    # ──────────────────────────────────────────────────────────────────────────────
    # Cookie presence logger for Google flows (optional, controlled by env)
    # ──────────────────────────────────────────────────────────────────────────────
    async def _install_google_cookie_logger(self, page: Page, session_id: str) -> None:
        if os.getenv('GOOGLE_COOKIE_DEBUG_LOG', 'true').lower() != 'true':
            return
        self._cookie_log_state.setdefault(session_id, {"apex_logged": False, "docs_logged": False})

        async def analyze(url: str):
            try:
                host = (urlparse(url).hostname or '').lower()
                if not host:
                    return
                if not self._cookie_log_state.get(session_id):
                    self._cookie_log_state[session_id] = {"apex_logged": False, "docs_logged": False}

                # Fetch cookies via CDP for full fidelity
                cdp = await page.context.new_cdp_session(page)
                all_cookies = (await cdp.send('Network.getAllCookies')).get('cookies', [])

                def names_for(domain: str) -> List[str]:
                    return sorted(list({c.get('name') for c in all_cookies if c.get('domain') == domain}))

                # Apply pending cookies after Google navigation using CDP for better stealth
                if ('google.com' in host) and hasattr(self, '_pending_cookies') and session_id in self._pending_cookies:
                    try:
                        pending_cookies = self._pending_cookies[session_id]
                        
                        # Try CDP approach for critical Google cookies
                        cdp = await page.context.new_cdp_session(page)
                        google_cookies = [c for c in pending_cookies if 'google.com' in c.get('domain', '')]
                        
                        for cookie in google_cookies:
                            try:
                                # Use CDP to set cookies directly
                                await cdp.send('Network.setCookie', {
                                    'name': cookie['name'],
                                    'value': cookie['value'],
                                    'domain': cookie.get('domain', ''),
                                    'path': cookie.get('path', '/'),
                                    'expires': cookie.get('expires', 0),
                                    'httpOnly': cookie.get('httpOnly', False),
                                    'secure': cookie.get('secure', True),
                                    'sameSite': cookie.get('sameSite', 'Lax')
                                })
                            except Exception as cookie_error:
                                logger.debug(f"[CookieDebug] Failed to set {cookie['name']} via CDP: {cookie_error}")
                        
                        await cdp.detach()
                        
                        # Also try the standard approach
                        await page.context.add_cookies(pending_cookies)
                        
                        logger.info(f"[CookieDebug] Applied {len(google_cookies)} Google cookies via CDP + {len(pending_cookies)} total via context")
                        del self._pending_cookies[session_id]
                        
                        # Wait for cookies to settle
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"[CookieDebug] Failed to apply deferred cookies: {e}")

                # After google.com hop: check apex cookies
                if ('google.com' in host) and (not self._cookie_log_state[session_id]["apex_logged"]):
                    apex = names_for('.google.com') + names_for('google.com') + names_for('www.google.com')
                    present = {n: (n in apex) for n in ['SID', 'SIDCC', 'APISID']}
                    
                    # Log all cookies found on google.com domains for debugging
                    google_domains = ['.google.com', 'google.com', 'www.google.com']
                    all_google_cookies = [c for c in all_cookies if c.get('domain') in google_domains]
                    logger.info(f"[GoogleCookieCheck] All cookies on google.com domains: {[(c['name'], c['domain']) for c in all_google_cookies]}")
                    
                    # Check if the cookies we set are actually there
                    for name in ['SID', 'SIDCC', 'APISID']:
                        cookie = next((c for c in all_google_cookies if c['name'] == name), None)
                        if cookie:
                            logger.info(f"[GoogleCookieCheck] {name} found: domain={cookie.get('domain')}, secure={cookie.get('secure')}, httpOnly={cookie.get('httpOnly')}, sameSite={cookie.get('sameSite')}")
                        else:
                            logger.warning(f"[GoogleCookieCheck] {name} NOT FOUND in browser cookies!")
                    
                    logger.info(f"[GoogleCookieCheck] Apex .google.com after navigation: {present}")
                    self._cookie_log_state[session_id]["apex_logged"] = True

                # After docs: check OSID
                if ('docs.google.com' in host) and (not self._cookie_log_state[session_id]["docs_logged"]):
                    docs = names_for('.docs.google.com') + names_for('docs.google.com')
                    has_osid = ('OSID' in docs) or ('__Secure-OSID' in docs)
                    logger.info(f"[GoogleCookieCheck] Docs cookies after navigation: OSID present={has_osid}")
                    if has_osid:
                        logger.info("[GoogleCookieCheck] ✅ Docs OSID detected — safe to persist cloud profile and stop re-copying Google cookies for this user.")
                    self._cookie_log_state[session_id]["docs_logged"] = True
            except Exception as _e:
                logger.debug(f"Cookie analysis error: {_e}")

        def on_framenavigated(frame):
            try:
                url = getattr(frame, 'url', '')
                if url:
                    asyncio.create_task(analyze(url))
            except Exception:
                pass

        # Hook navigation handler
        page.on('framenavigated', on_framenavigated)

        # Also analyze current URL immediately
        try:
            await analyze(await page.evaluate("() => location.href"))
        except Exception:
            pass
    
    async def _setup_screensaver(self, page: Page, session_id: str) -> None:
        """
        Setup screensaver for visual mode with verification.
        
        Raises:
            RuntimeError: If screensaver setup fails
        """
        try:
            logger.debug(f"Setting up screensaver for session {session_id}")
            
            # Navigate to about:blank first if needed
            if page.url == '' or page.url == 'about:blank':
                await page.goto('about:blank', timeout=10000)
            
            # Show the real bouncing DVD screensaver (with JavaScript physics)
            await show_custom_dvd_screensaver(page)
            
            # 🎯 SIMPLE: Verify rich content was created (static approach guarantees success)
            content_check = await page.evaluate("""
                () => {
                    const overlay = document.getElementById('pretty-loading-animation');
                    const totalElements = document.querySelectorAll('*').length;
                    const sparkles = document.querySelectorAll('.sparkle').length;
                    
                    return {
                        overlayExists: !!overlay,
                        totalElements: totalElements,
                        sparkles: sparkles,
                        richContent: totalElements > 30  // Static approach should create 40+ elements
                    };
                }
            """)
            
            if content_check['richContent']:
                logger.info(f"✅ Rich screensaver content created for session {session_id}")
                logger.info(f"   Total elements: {content_check['totalElements']}")
                logger.info(f"   Sparkles: {content_check['sparkles']}")
            else:
                logger.warning(f"⚠️ Expected rich content but only got {content_check['totalElements']} elements")
            
            logger.debug(f"Static screensaver setup completed for session {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to setup screensaver for session {session_id}: {e}")
            raise RuntimeError(f"Screensaver setup failed: {e}")
    
    async def _cleanup_failed_creation(self, session_id: str) -> None:
        """Clean up any partial state from failed browser creation"""
        try:
            # Remove from active sessions if present
            if session_id in self._active_sessions:
                session_info = self._active_sessions[session_id]
                
                # Try to close browser if it was created
                browser = session_info.get('browser')
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass  # Ignore cleanup errors
                
                del self._active_sessions[session_id]
            
            # Clean up profile
            profile_manager.cleanup_session(session_id)
            
        except Exception as e:
            logger.debug(f"Error during failed creation cleanup for session {session_id}: {e}")


# Global factory instance
browser_factory = BrowserFactory()
