"""
Visual Workflow Browser with rrweb Recording Capabilities

This module provides enhanced browser functionality for capturing and streaming
visual workflow execution using rrweb technology.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from collections import deque
from typing import Optional, Callable, Dict, Any
from browser_use import Browser
from browser_use.browser.browser import BrowserProfile
from .profile_manager import profile_manager
from .rrweb_config import (
    get_throttling_script, 
    get_recording_options_js, 
    get_cdn_urls, 
    get_timing_config,
    get_performance_config
)

logger = logging.getLogger(__name__)


class VisualWorkflowBrowser:
    """Enhanced browser with rrweb recording capabilities for visual workflow streaming"""
    
    def __init__(self, session_id: str, event_callback: Optional[Callable] = None, browser: Optional[Browser] = None):
        self.session_id = session_id
        self.browser: Optional[Browser] = browser  # Accept existing browser instance
        self.page = None
        self.recording_active = False
        self.event_callback = event_callback
        self.event_queue = asyncio.Queue()
        self.rrweb_injected = False
        self._owns_browser = browser is None  # Track if we created the browser
        
        # Load configuration
        self.timing_config = get_timing_config()
        self.performance_config = get_performance_config()
        
        # Event buffer for reconnection scenarios
        buffer_size = self.performance_config.get("event_buffer_size", 1000)
        self.event_buffer = deque(maxlen=buffer_size)
        
        # rrweb CDN URLs from config
        self.rrweb_cdn_url, self.rrweb_fallback_url = get_cdn_urls()
    
    async def create_browser(self, headless: bool = True, user_id: Optional[str] = None) -> Browser:
        """Create browser instance optimized for visual workflow execution"""
        try:
            # If browser already provided, use it
            if self.browser is not None:
                logger.info(f"Using existing browser instance for session {self.session_id}")
                self.page = await self.browser.get_current_page()
                
                # Don't navigate away - use the current page for rrweb injection
                current_url = self.page.url
                logger.info(f"Using existing browser with URL: {current_url}")
                
                # Set longer timeouts to prevent premature closure
                self.page.set_default_timeout(60000)  # 60 seconds
                
                logger.info(f"Visual browser initialized with existing instance for session {self.session_id}")
                return self.browser
            
            # Create new browser only if none provided
            # 👩‍🦳 Use ProfileManager for directory management
            config = profile_manager.create_browser_profile_config(
                session_id=self.session_id,
                user_id=user_id  # Optional: for future user profile features
            )
            
            # Override with method parameters
            config.update({
                'headless': headless
            })
            
            logger.info(f"Creating new browser with session directory: {config['user_data_dir']}")
            
            profile = BrowserProfile(**config)
            
            self.browser = Browser(browser_profile=profile)
            await self.browser.start()
            self.page = await self.browser.get_current_page()
            
            # Don't navigate away from about:blank - rrweb works fine on any page
            current_url = self.page.url
            logger.info(f"Browser started with URL: {current_url}")
            logger.info(f"Keeping browser on current page for rrweb injection")
            
            # Set longer timeouts to prevent premature closure
            self.page.set_default_timeout(60000)  # 60 seconds
            
            logger.info(f"Visual browser created for session {self.session_id}")
            return self.browser
            
        except Exception as e:
            logger.error(f"❌Failed to create visual browser: {e}")
            raise
    
    async def inject_rrweb(self) -> bool:
        """Inject rrweb recording script into the browser page - OPTIMIZED FOR SPEED"""
        if not self.page:
            raise RuntimeError("Browser page not available. Call create_browser() first.")
        
        try:
            # Don't navigate away - inject rrweb on whatever page we're currently on
            # rrweb works fine on about:blank and will capture navigation events
            current_url = self.page.url
            logger.info(f"Injecting rrweb on current page: {current_url}")
            
            # Enhanced rrweb injection script with configuration from config file
            throttling_script = get_throttling_script()
            recording_options = get_recording_options_js()
            
            rrweb_injection_script = f"""
            (function() {{
                console.log('Starting rrweb injection...');
                
                // Stop any existing recording first
                if (window.rrwebStopRecording && typeof window.rrwebStopRecording === 'function') {{
                    console.log('Stopping existing rrweb recording...');
                    try {{
                        window.rrwebStopRecording();
                        window.rrwebStopRecording = null;
                    }} catch (e) {{
                        console.warn('Error stopping existing recording:', e);
                    }}
                }}
                
                // Check if rrweb is already loaded
                if (window.rrweb) {{
                    console.log('rrweb already loaded, starting fresh recording...');
                    startRecording();
                    return;
                }}
                
                // Load rrweb from CDN with fallback
                const script = document.createElement('script');
                script.src = '{self.rrweb_cdn_url}';
                script.async = true;
                
                script.onload = function() {{
                    console.log('rrweb loaded successfully from CDN');
                    startRecording();
                }};
                
                script.onerror = function() {{
                    console.error('Failed to load rrweb from CDN, trying alternative...');
                    // Try alternative CDN
                    const altScript = document.createElement('script');
                    altScript.src = '{self.rrweb_fallback_url}';
                    altScript.onload = function() {{
                        console.log('rrweb loaded from alternative CDN');
                        startRecording();
                    }};
                    altScript.onerror = function() {{
                        console.error('All rrweb CDN sources failed');
                        // Send error to backend
                        if (window.sendRRWebEvent) {{
                            window.sendRRWebEvent(JSON.stringify({{
                                type: 5,  // Custom event type for errors
                                data: {{
                                    tag: 'error',
                                    payload: {{
                                        message: 'Failed to load rrweb script'
                                    }}
                                }},
                                timestamp: Date.now()
                            }}));
                        }}
                    }};
                    document.head.appendChild(altScript);
                }};
                
                document.head.appendChild(script);
                
                function startRecording() {{
                    try {{
                        // Start recording with configuration from config file
                        window.rrwebStopRecording = rrweb.record({{
                            emit(event) {{
                                {throttling_script}
                            }},
                            ...{recording_options}
                        }});
                        
                        console.log('rrweb recording started successfully with configuration');
                        
                        // Log iframe detection
                        const iframes = document.querySelectorAll('iframe');
                        console.log(`Detected ${{iframes.length}} iframes on page`);
                        
                        // Send success event with proper numeric type
                        if (window.sendRRWebEvent) {{
                            window.sendRRWebEvent(JSON.stringify({{
                                type: 4,  // Meta event type as number, not string
                                data: {{
                                    href: window.location.href,
                                    width: window.innerWidth,
                                    height: window.innerHeight,
                                    iframeCount: iframes.length,
                                    crossOriginEnabled: true,
                                    userAgent: navigator.userAgent.substring(0, 50)
                                }},
                                timestamp: Date.now()
                            }}));
                        }}
                        
                        // Listen for navigation events to send new full snapshots (only if not already set)
                        if (!window._rrwebNavigationListenersSet) {{
                            window.addEventListener('beforeunload', function() {{
                                console.log('Page unloading - navigation detected');
                            }});
                            
                            window.addEventListener('load', function() {{
                                console.log('New page loaded - sending fresh meta event');
                                if (window.sendRRWebEvent) {{
                                    window.sendRRWebEvent(JSON.stringify({{
                                        type: 4,  // Meta event for new page
                                        data: {{
                                            href: window.location.href,
                                            width: window.innerWidth,
                                            height: window.innerHeight,
                                            pageLoad: true
                                        }},
                                        timestamp: Date.now()
                                    }}));
                                }}
                            }});
                            
                            window._rrwebNavigationListenersSet = true;
                        }}
                        
                    }} catch (e) {{
                        console.error('Failed to start rrweb recording:', e);
                        if (window.sendRRWebEvent) {{
                            window.sendRRWebEvent(JSON.stringify({{
                                type: 5,  // Custom event type for errors
                                data: {{
                                    tag: 'error',
                                    payload: {{
                                        message: 'Failed to start recording: ' + e.message
                                    }}
                                }},
                                timestamp: Date.now()
                            }}));
                        }}
                    }}
                }}
            }})();
            """
            
            # Expose function to receive rrweb events FIRST (only if not already exposed)
            try:
                await self.page.expose_function('sendRRWebEvent', self._handle_rrweb_event)
                logger.info(f"Exposed sendRRWebEvent function for session {self.session_id}")
            except Exception as e:
                if "already registered" in str(e):
                    logger.info(f"sendRRWebEvent function already registered for session {self.session_id}")
                else:
                    logger.error(f"❌Failed to expose sendRRWebEvent function: {e}")
                    raise
            
            # Execute the injection script
            await self.page.evaluate(rrweb_injection_script)
            
            self.rrweb_injected = True
            logger.info(f"rrweb injected successfully for session {self.session_id}")
            
            # Wait for rrweb to load and start recording (from config)
            injection_delay = self.timing_config.get("injection_delay", 1.5)
            await asyncio.sleep(injection_delay)
            
            # Verify recording is active
            recording_status = await self.page.evaluate("""
                () => {
                    return {
                        rrweb_loaded: typeof window.rrweb !== 'undefined',
                        recording_active: typeof window.rrwebStopRecording === 'function',
                        url: window.location.href
                    };
                }
            """)
            
            logger.info(f"rrweb status: {recording_status}")
            
            return recording_status.get('recording_active', False)
            
        except Exception as e:
            logger.error(f"❌Failed to inject rrweb: {e}")
            return False
    
    async def _handle_rrweb_event(self, event_json: str) -> None:
        """Handle rrweb events received from the browser"""
        try:
            event_data = json.loads(event_json)
            
            # Add metadata
            enhanced_event = {
                'session_id': self.session_id,
                'timestamp': asyncio.get_event_loop().time(),
                'event': event_data
            }
            
            # Add to buffer
            self.event_buffer.append(enhanced_event)
            
            # Add to queue for processing
            await self.event_queue.put(enhanced_event)
            
            # Call callback if provided
            if self.event_callback:
                try:
                    await self.event_callback(enhanced_event)
                except Exception as e:
                    logger.error(f"❌Error in event callback: {e}")
                    
        except Exception as e:
            logger.error(f"❌Error handling rrweb event: {e}")
    
    async def start_recording(self) -> bool:
        """Start rrweb recording (injection should be done first)"""
        if not self.rrweb_injected:
            logger.warning("rrweb not injected yet, injecting now...")
            await self.inject_rrweb()
        
        self.recording_active = True
        logger.info(f"rrweb recording started for session {self.session_id}")
        return True
    
    async def stop_recording(self) -> bool:
        """Stop rrweb recording"""
        if not self.page:
            return False
            
        try:
            # Stop recording in browser
            await self.page.evaluate("""
                if (window.rrwebStopRecording) {
                    window.rrwebStopRecording();
                    console.log('rrweb recording stopped');
                }
            """)
            
            self.recording_active = False
            logger.info(f"rrweb recording stopped for session {self.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌Error stopping rrweb recording: {e}")
            return False
    
    async def get_buffered_events(self) -> list:
        """Get all buffered events for reconnection scenarios"""
        return list(self.event_buffer)
    
    async def navigate_to(self, url: str) -> None:
        """Navigate to URL with rrweb recording - OPTIMIZED FOR SPEED"""
        if not self.page:
            raise RuntimeError("Browser page not available")
        
        logger.info(f"Navigating to {url} for session {self.session_id}")
        await self.page.goto(url, wait_until='domcontentloaded')
        
        # Re-inject rrweb after navigation to capture new page
        if self.recording_active:
            logger.info(f"Re-injecting rrweb after navigation to {url}")
            navigation_delay = self.timing_config.get("navigation_delay", 1.0)
            await asyncio.sleep(navigation_delay)  # Wait for page to load (from config)
            success = await self.inject_rrweb()
            if success:
                logger.info(f"rrweb successfully re-injected for {url}")
            else:
                logger.warning(f"Failed to re-inject rrweb for {url}")
    
    async def execute_workflow_step(self, step_function: Callable, *args, **kwargs) -> Any:
        """Execute a workflow step while maintaining rrweb recording"""
        try:
            result = await step_function(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"❌Error executing workflow step: {e}")
            raise
    
    async def cleanup(self) -> None:
        """Clean up browser resources"""
        try:
            if self.recording_active:
                await self.stop_recording()
            
            # Only close browser if we created it (not if it was passed to us)
            if self.browser and self._owns_browser:
                try:
                    await self.browser.close()
                    logger.info(f"Visual browser closed for session {self.session_id}")
                except Exception as e:
                    logger.warning(f"Error closing browser for session {self.session_id}: {e}")
                finally:
                    self.page = None
                    self.browser = None
            elif self.browser and not self._owns_browser:
                logger.info(f"Visual browser cleanup: skipping browser close (not owned) for session {self.session_id}")
                self.page = None
                # Don't set browser to None since we don't own it
            
            # 👩‍🦳: Use ProfileManager for session cleanup (only if we created the browser)
            if self._owns_browser:
                profile_manager.cleanup_session(self.session_id)
            
            logger.info(f"Visual browser cleaned up for session {self.session_id}")
            
        except Exception as e:
            logger.error(f"❌Error during cleanup: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the visual browser"""
        return {
            'session_id': self.session_id,
            'browser_active': self.browser is not None,
            'recording_active': self.recording_active,
            'rrweb_injected': self.rrweb_injected,
            'buffered_events': len(self.event_buffer),
            'queue_size': self.event_queue.qsize()
        } 