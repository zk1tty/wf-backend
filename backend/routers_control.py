"""
Control Channel Router - Remote Browser Control via WebSocket

This module provides the Control Channel WebSocket endpoint that forwards
user input (mouse/keyboard) from the frontend to the remote browser via Patchright
(monkey-patched Playwright for better stealth).

All events are logged using LoggerAdapter with execution_id set to session_id,
so they can be received via the existing /ws/logs/{execution_id} endpoint.

Note: The Page object comes from browser_factory which uses Patchright internally
via monkey-patching of playwright.async_api.async_playwright.
"""

import os
import time
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Control Channel router
control_router = APIRouter(prefix='/workflows/visual')

# Debug mode: Set CONTROL_CHANNEL_DEBUG=true to log actual keyboard characters
# WARNING: Only enable for debugging! Logs will contain passwords!
DEBUG_LOG_KEYS = os.getenv('CONTROL_CHANNEL_DEBUG', 'false').lower() == 'true'

if DEBUG_LOG_KEYS:
    logger.warning("⚠️  [ControlChannel] DEBUG MODE ENABLED - Keyboard characters will be logged (INSECURE!)")
else:
    logger.info("🔒 [ControlChannel] Secure mode - Keyboard characters NOT logged")


@control_router.websocket("/{session_id}/control")
async def control_channel_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for Control Channel - forward user input to remote browser
    
    Protocol:
    - Client sends: {session_id, message: {type, action, x, y, key, ...}}
    - Server executes: page.mouse.click(), page.keyboard.press(), etc. (via Patchright)
    - Server responds: {type: 'ack'} or {type: 'error'}
    
    Browser Automation:
    - Uses Patchright (stealth Playwright fork) for better anti-detection
    - Page object from browser_factory already configured with Patchright
    
    Security:
    - Session validation
    - Input masking in rrweb (password fields masked)
    - No logging of actual keyboard characters (passwords)
    
    Logging:
    - All events logged via LoggerAdapter with execution_id=session_id
    - Logs available at /ws/logs/{session_id}
    """
    # Track connection start time
    connection_start = time.time()
    
    # Create LoggerAdapter with execution_id for log broadcasting
    # This allows logs to be received via /ws/logs/{session_id}
    control_logger = logging.LoggerAdapter(logger, extra={'execution_id': session_id})
    
    try:
        # ========================================
        # Session Validation & Normalization
        # ========================================
        original_session_id = session_id
        
        # Normalize session ID (handle with/without 'visual-' prefix)
        if not session_id.startswith("visual-"):
            try:
                import uuid
                uuid.UUID(session_id)  # Validate UUID format
                session_id = f"visual-{session_id}"
                control_logger.info(f"[ControlChannel] Normalized session ID: '{original_session_id}' → '{session_id}'")
                # Update logger adapter with normalized session_id
                control_logger = logging.LoggerAdapter(logger, extra={'execution_id': session_id})
            except ValueError:
                # Invalid session ID format
                await websocket.accept()
                await websocket.send_json({
                    "type": "error",
                    "error_type": "invalid_message",
                    "error": f"Invalid session ID format: {original_session_id}",
                    "timestamp": time.time()
                })
                await websocket.close(code=4400, reason="Invalid session ID")
                return
        
        # Get browser instance from BrowserFactory
        try:
            from workflow_use.browser.browser_factory import browser_factory
        except ImportError as e:
            control_logger.error(f"[ControlChannel] Failed to import browser_factory: {e}")
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "error_type": "browser_not_ready",
                "error": "Browser factory not available",
                "timestamp": time.time()
            })
            await websocket.close(code=5503, reason="Service unavailable")
            return
        
        # Validate session exists
        browser = await browser_factory.get_browser_for_session(session_id)
        if not browser:
            control_logger.warning(f"[ControlChannel] Session not found: {session_id}")
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "error_type": "session_not_found",
                "error": f"Session {session_id} not found or expired",
                "timestamp": time.time()
            })
            await websocket.close(code=4404, reason="Session not found")
            return
        
        # Get Playwright page object
        try:
            page = await browser.get_current_page()
            if not page:
                raise RuntimeError("Page not available")
        except Exception as e:
            control_logger.error(f"[ControlChannel] Failed to get page: {e}")
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "error_type": "browser_not_ready",
                "error": "Browser page not available",
                "timestamp": time.time()
            })
            await websocket.close(code=4503, reason="Browser not ready")
            return
        
        # Accept WebSocket connection
        await websocket.accept()
        
        # Send connection established message
        await websocket.send_json({
            "type": "connection_established",
            "session_id": session_id,
            "timestamp": time.time()
        })
        
        # Log connection event (broadcasted via /ws/logs/{session_id})
        control_logger.info(f"[ControlChannel] ✅ Connected to control channel - Waiting for input...")
        
        # ========================================
        # Main Message Loop
        # ========================================
        try:
            message_count = 0
            while True:
                # Receive message from client
                try:
                    data = await websocket.receive_json()
                    message_count += 1
                except WebSocketDisconnect:
                    control_logger.info(f"[ControlChannel] Client disconnected (received {message_count} messages)")
                    break
                
                # Extract message wrapper
                message = data.get('message', {})
                
                # Message Validation - check wrapper format
                if not message or not isinstance(message, dict):
                    await websocket.send_json({
                        "type": "error",
                        "error_type": "invalid_message",
                        "error": "Missing or invalid 'message' field",
                        "timestamp": time.time()
                    })
                    continue
                
                message_type = message.get('type')
                
                # Validate message type
                if not message_type:
                    await websocket.send_json({
                        "type": "error",
                        "error_type": "invalid_message",
                        "error": "Missing 'type' field in message",
                        "timestamp": time.time()
                    })
                    continue
                
                try:
                    # Route by Message Type
                    if message_type == 'mouse':
                        await handle_mouse_message(page, message, websocket, control_logger)
                    
                    elif message_type == 'keyboard':
                        await handle_keyboard_message(page, message, websocket, control_logger)
                    
                    elif message_type == 'wheel':
                        await handle_wheel_message(page, message, websocket, control_logger)
                    
                    else:
                        # Unknown message type
                        await websocket.send_json({
                            "type": "error",
                            "error_type": "invalid_message",
                            "error": f"Unknown message type: {message_type}",
                            "timestamp": time.time()
                        })
                        continue
                    
                    # Send Acknowledgment
                    await websocket.send_json({
                        "type": "ack",
                        "timestamp": time.time(),
                        "message": "Command executed successfully"
                    })
                
                except Exception as e:
                    # Error handling - execution failed
                    control_logger.error(f"[ControlChannel] Execution failed: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "error_type": "execution_failed",
                        "error": str(e),
                        "timestamp": time.time()
                    })
        
        except WebSocketDisconnect:
            control_logger.info(f"[ControlChannel] Disconnected")
        except Exception as e:
            control_logger.error(f"[ControlChannel] Error in message loop: {e}")
        
        finally:
            # Log session end
            duration = time.time() - connection_start
            control_logger.info(f"[ControlChannel] ✅ Session ended, duration={duration:.2f}s")
    
    except Exception as e:
        control_logger.error(f"[ControlChannel] Fatal error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error_type": "execution_failed",
                "error": str(e),
                "timestamp": time.time()
            })
            await websocket.close()
        except:
            pass


# ============================================================================
# Message Handlers
# ============================================================================

async def handle_mouse_message(page, message: dict, websocket: WebSocket, control_logger):
    """
    Handle mouse control messages
    
    Supports: click, move, down, up, dblclick
    
    Args:
        page: Playwright page object
        message: Control message dict
        websocket: WebSocket connection
        control_logger: LoggerAdapter with execution_id for broadcasting
    """
    action = message.get('action')
    x = message.get('x')
    y = message.get('y')
    button = message.get('button', 'left')
    
    # Validate required fields
    if action is None or x is None or y is None:
        await websocket.send_json({
            "type": "error",
            "error_type": "invalid_message",
            "error": "Mouse message missing required fields: action, x, y",
            "timestamp": time.time()
        })
        return
    
    # Validate coordinates (bounds check)
    if not (0 <= x <= 10000) or not (0 <= y <= 10000):
        await websocket.send_json({
            "type": "error",
            "error_type": "invalid_message",
            "error": f"Invalid coordinates: x={x}, y={y} (must be 0-10000)",
            "timestamp": time.time()
        })
        return
    
    # Execute mouse action
    if action == 'click':
        await page.mouse.click(x, y, button=button)
        control_logger.info(f"[ControlChannel] 🖱️  Mouse click: ({x}, {y})")
    
    elif action == 'move':
        await page.mouse.move(x, y)
        # Mouse moves are too noisy - don't log
    
    elif action == 'down':
        await page.mouse.move(x, y)
        await page.mouse.down(button=button)
    
    elif action == 'up':
        await page.mouse.up(button=button)
    
    elif action == 'dblclick':
        await page.mouse.dblclick(x, y)
        control_logger.info(f"[ControlChannel] 🖱️  Double-click: ({x}, {y})")
    
    else:
        await websocket.send_json({
            "type": "error",
            "error_type": "invalid_message",
            "error": f"Unknown mouse action: {action}",
            "timestamp": time.time()
        })


async def handle_keyboard_message(page, message: dict, websocket: WebSocket, control_logger):
    """
    Handle keyboard control messages
    
    Supports: down, up actions
    
    Args:
        page: Playwright page object
        message: Control message dict
        websocket: WebSocket connection
        control_logger: LoggerAdapter with execution_id for broadcasting
    
    Security Note:
    - Does NOT log actual key characters (could be passwords)
    - Only logs action types and special key names
    """
    try:
        action = message.get('action')
        key = message.get('key')
        
        # Validate required fields
        if action is None or key is None:
            await websocket.send_json({
                "type": "error",
                "error_type": "invalid_message",
                "error": "Keyboard message missing required fields: action, key",
                "timestamp": time.time()
            })
            return
        
        # Execute keyboard action
        if action == 'down':
            # For single printable characters, use press() which handles both down and up
            if len(key) == 1:
                await page.keyboard.press(key)
                # SECURITY: DO NOT log the actual key (could be password)
                # Only log character if DEBUG mode is enabled
                if DEBUG_LOG_KEYS:
                    control_logger.info(f"[ControlChannel] ⌨️  Keyboard: char='{key}' (DEBUG MODE)")
                else:
                    control_logger.info(f"[ControlChannel] ⌨️  Keyboard: character input")
            else:
                # For special keys (Enter, Tab, Backspace, etc.)
                await page.keyboard.down(key)
                control_logger.info(f"[ControlChannel] ⌨️  Keyboard: special key '{key}'")
        
        elif action == 'up':
            await page.keyboard.up(key)
            # Key up events are too noisy - don't log
        
        else:
            await websocket.send_json({
                "type": "error",
                "error_type": "invalid_message",
                "error": f"Unknown keyboard action: {action}",
                "timestamp": time.time()
            })
    
    except Exception as e:
        control_logger.error(f"[ControlChannel] ❌ Keyboard handler exception: {e}")
        raise


async def handle_wheel_message(page, message: dict, websocket: WebSocket, control_logger):
    """
    Handle mouse wheel scroll messages
    
    Args:
        page: Playwright page object
        message: Control message dict
        websocket: WebSocket connection
        control_logger: LoggerAdapter with execution_id for broadcasting
    """
    delta_x = message.get('deltaX', 0)
    delta_y = message.get('deltaY', 0)
    
    # Execute wheel scroll
    await page.mouse.wheel(delta_x, delta_y)
    # Wheel events are too noisy - don't log