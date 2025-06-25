"""
rrweb Recording Configuration

Centralized configuration for rrweb visual recording and streaming.
This file contains all the settings for event throttling, recording options,
and performance optimization.
"""

from typing import Dict, Any

# Event Throttling Configuration
THROTTLING_CONFIG = {
    "max_events_per_second": 10,  # Limit to prevent frontend overload
    "reset_interval_ms": 1000,    # Reset counter every second
    "enable_throttling": True,    # Can be disabled for debugging
}

# rrweb CDN Configuration
CDN_CONFIG = {
    "primary_url": "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/rrweb.min.js",
    "fallback_url": "https://unpkg.com/rrweb@latest/dist/rrweb.min.js",
    "load_timeout": 10000,  # 10 seconds timeout for CDN loading
}

# rrweb Recording Options (optimized for performance)
RECORDING_OPTIONS = {
    "recordCanvas": True,
    "recordCrossOriginIframes": True,
    "checkoutEveryNms": 5000,  # Checkpoint every 5 seconds (demo config)
    "packFn": "rrweb.pack",    # Enable compression
    "sampling": {
        "scroll": 100,    # 100ms between scroll events (demo config)
        "media": 400,     # 400ms between media events (demo config)
        "input": "last"   # Only capture final input values
    },
    "slimDOMOptions": {
        "script": False,
        "comment": False,
        "headFavicon": False,
        "headWhitespace": False,
        "headMetaSocial": False,
        "headMetaRobots": False,
        "headMetaHttpEquiv": False,
        "headMetaVerification": False
    },
    "maskTextClass": "rr-mask",
    "blockClass": "rr-block",
    "ignoreClass": "rr-ignore",
    "inlineStylesheet": True
}

# Timing Configuration
TIMING_CONFIG = {
    "injection_delay": 1.5,      # Wait after rrweb injection
    "recording_stabilization": 0.5,  # Wait for recording to stabilize
    "navigation_delay": 1.0,     # Wait after navigation
    "page_load_timeout": 30000,  # 30 seconds
}

# Performance Configuration
PERFORMANCE_CONFIG = {
    "event_buffer_size": 1000,   # Max events to buffer per session
    "enable_compression": True,   # Use rrweb.pack for compression
    "enable_console_logging": True,  # Log rrweb events in browser console
}

def get_throttling_script() -> str:
    """Generate JavaScript code for event throttling"""
    config = THROTTLING_CONFIG
    
    if not config["enable_throttling"]:
        return """
        // Throttling disabled - send all events
        if (window.sendRRWebEvent) {
            try {
                window.sendRRWebEvent(JSON.stringify(event));
            } catch (e) {
                console.error('Failed to send rrweb event:', e);
            }
        }
        """
    
    return f"""
    // SIMPLE THROTTLING: Limit events to max {config["max_events_per_second"]} per second
    const now = Date.now();
    window._lastEventTime = window._lastEventTime || 0;
    window._eventCount = window._eventCount || 0;
    
    // Reset counter every {config["reset_interval_ms"]}ms
    if (now - window._lastEventTime >= {config["reset_interval_ms"]}) {{
        window._eventCount = 0;
        window._lastEventTime = now;
    }}
    
    // Skip if we've already sent {config["max_events_per_second"]} events this second
    if (window._eventCount >= {config["max_events_per_second"]}) {{
        return;
    }}
    
    window._eventCount++;
    
    // Send event to backend via exposed function
    if (window.sendRRWebEvent) {{
        try {{
            window.sendRRWebEvent(JSON.stringify(event));
        }} catch (e) {{
            console.error('Failed to send rrweb event:', e);
        }}
    }}
    """

def get_recording_options_js() -> str:
    """Generate JavaScript object for rrweb recording options"""
    options = RECORDING_OPTIONS.copy()
    
    # Convert Python boolean to JavaScript
    def py_to_js(obj):
        if isinstance(obj, bool):
            return "true" if obj else "false"
        elif isinstance(obj, dict):
            items = [f'"{k}": {py_to_js(v)}' for k, v in obj.items()]
            return "{" + ", ".join(items) + "}"
        elif isinstance(obj, str):
            return f'"{obj}"'
        else:
            return str(obj)
    
    # Build the JavaScript object
    js_options = []
    for key, value in options.items():
        if key == "packFn":
            js_options.append(f"{key}: {value}")  # Don't quote function name
        else:
            js_options.append(f"{key}: {py_to_js(value)}")
    
    return "{" + ", ".join(js_options) + "}"

def get_cdn_urls() -> tuple:
    """Get primary and fallback CDN URLs"""
    return CDN_CONFIG["primary_url"], CDN_CONFIG["fallback_url"]

def get_timing_config() -> Dict[str, float]:
    """Get timing configuration for delays"""
    return TIMING_CONFIG.copy()

def get_performance_config() -> Dict[str, Any]:
    """Get performance configuration"""
    return PERFORMANCE_CONFIG.copy()

# Export commonly used configurations
__all__ = [
    'THROTTLING_CONFIG',
    'CDN_CONFIG', 
    'RECORDING_OPTIONS',
    'TIMING_CONFIG',
    'PERFORMANCE_CONFIG',
    'get_throttling_script',
    'get_recording_options_js',
    'get_cdn_urls',
    'get_timing_config',
    'get_performance_config'
] 