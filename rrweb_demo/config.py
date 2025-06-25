"""
rrweb Demo Configuration

Centralized configuration for the visual streaming demo system.
"""

import os
from typing import Dict, Any

# Server Configuration
SERVER_CONFIG = {
    "host": os.getenv("RRWEB_HOST", "0.0.0.0"),
    "port": int(os.getenv("RRWEB_PORT", 8000)),
    "reload": os.getenv("RRWEB_RELOAD", "false").lower() == "true",
    "log_level": os.getenv("RRWEB_LOG_LEVEL", "info"),
}

# Demo Workflow Configuration
DEMO_CONFIG = {
    "default_session_id": "demo-session-123",
    "workflow_steps": 5,
    "target_url": "https://example.com",
    "navigation_url": "https://httpbin.org/html",
    "step_delay": 1.0,  # seconds between steps (optimized from 3.0)
    "micro_interaction_delay": 0.1,  # seconds for micro-interactions
}

# Browser Configuration
BROWSER_CONFIG = {
    "headless": False,  # Set to True for production
    "devtools": False,
    "timeout": 60000,  # 60 seconds
    "navigation_timeout": 30000,  # 30 seconds
    "disable_security": True,
    "keep_alive": False,  # Force new instances for demo
}

# rrweb Recording Configuration
RRWEB_CONFIG = {
    "cdn_url": "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/rrweb.min.js",
    "fallback_cdn_url": "https://unpkg.com/rrweb@latest/dist/rrweb.min.js",
    "injection_delay": 1.5,  # seconds to wait after injection (optimized from 3.0)
    "recording_stabilization_delay": 0.5,  # seconds (optimized from 2.0)
    "navigation_delay": 1.0,  # seconds after navigation (optimized from 2.0)
    
    # rrweb recording options
    "recording_options": {
        "recordCanvas": True,
        "recordCrossOriginIframes": True,
        "checkoutEveryNms": 5000,  # 5 seconds (optimized from 10s)
        "packFn": "rrweb.pack",  # Enable compression
        "sampling": {
            "scroll": 100,    # 100ms (optimized from 150ms)
            "media": 400,     # 400ms (optimized from 800ms)
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
}

# WebSocket Configuration
WEBSOCKET_CONFIG = {
    "max_connections_per_session": 10,
    "heartbeat_interval": 30,  # seconds
    "message_buffer_size": 1000,
    "reconnection_timeout": 5,  # seconds
}

# Performance Configuration
PERFORMANCE_CONFIG = {
    "event_buffer_size": 1000,  # Max events to buffer per session
    "max_concurrent_sessions": 50,
    "session_cleanup_delay": 300,  # 5 minutes after last client disconnects
    "browser_startup_timeout": 30,  # seconds
    "page_load_timeout": 30,  # seconds
}

# Monitoring Configuration
MONITORING_CONFIG = {
    "enable_statistics": True,
    "log_event_rates": True,
    "performance_monitoring": True,
    "health_check_interval": 60,  # seconds
}

# Development Configuration
DEV_CONFIG = {
    "debug_mode": os.getenv("RRWEB_DEBUG", "false").lower() == "true",
    "verbose_logging": os.getenv("RRWEB_VERBOSE", "false").lower() == "true",
    "enable_cors": True,
    "hot_reload": False,
}

# Production Configuration
PROD_CONFIG = {
    "debug_mode": False,
    "verbose_logging": False,
    "enable_cors": False,
    "security_headers": True,
    "rate_limiting": True,
    "session_encryption": True,
}

def get_config(environment: str = "development") -> Dict[str, Any]:
    """
    Get configuration based on environment
    
    Args:
        environment: 'development', 'production', or auto-detected from env var
    
    Returns:
        Combined configuration dictionary
    """
    if environment == "development":
        environment = os.getenv("RRWEB_ENV", "development")
    
    # Base configuration
    config = {
        "server": SERVER_CONFIG,
        "demo": DEMO_CONFIG,
        "browser": BROWSER_CONFIG,
        "rrweb": RRWEB_CONFIG,
        "websocket": WEBSOCKET_CONFIG,
        "performance": PERFORMANCE_CONFIG,
        "monitoring": MONITORING_CONFIG,
    }
    
    # Add environment-specific config
    if environment == "production":
        config["environment"] = PROD_CONFIG
        # Override some settings for production
        config["browser"]["headless"] = True
        config["server"]["reload"] = False
    else:
        config["environment"] = DEV_CONFIG
    
    return config

def get_browser_args() -> list:
    """Get optimized browser arguments"""
    return [
        '--disable-web-security',
        '--no-first-run',
        '--disable-default-browser-check',
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--disable-dev-shm-usage',
        '--no-sandbox',  # For cloud environments
        '--disable-background-timer-throttling',  # Prevent throttling
        '--disable-backgrounding-occluded-windows',  # Keep active
        '--disable-renderer-backgrounding',  # Keep renderer active
        '--disable-features=TranslateUI',  # Reduce popups
        '--disable-ipc-flooding-protection',  # Allow rapid events
        '--new-window'  # Force new window instead of reusing
    ]

# Export commonly used configurations
__all__ = [
    'SERVER_CONFIG',
    'DEMO_CONFIG', 
    'BROWSER_CONFIG',
    'RRWEB_CONFIG',
    'WEBSOCKET_CONFIG',
    'PERFORMANCE_CONFIG',
    'MONITORING_CONFIG',
    'get_config',
    'get_browser_args'
] 