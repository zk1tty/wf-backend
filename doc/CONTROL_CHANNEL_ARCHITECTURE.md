# Control Channel Architecture (Backend Implementation)

## Overview

This document outlines the backend implementation for the **Control Channel** WebSocket endpoint. The frontend is already implemented and expects the backend to match the exact protocol specification in `doc/CONTROL_CHANNEL.md`.

**Frontend Status**: ✅ Complete  
**Backend Status**: 🚧 In Progress  
**Priority**: High (required for one-time auth flows)

## Current Architecture

### Visual Streaming Flow
1. **Browser** (Chromium via Playwright) → rrweb recorder captures DOM events
2. **RRWebRecorder** (`workflow_use/rrweb/recorder.py`) → processes events
3. **RRWebEventStreamer** (`backend/rrweb/event_streamer.py`) → manages event queue and broadcasting
4. **WebSocketManager** (`backend/websocket_manager.py`) → manages client connections
5. **Client** → receives events via WebSocket and replays using rrweb.Replayer

### Browser Control Flow (Current - Workflow Execution Only)
1. **WorkflowController** (`workflow_use/controller/service.py`) → defines actions
2. **Playwright Page API** → executes actions:
   - `locator.click()` for clicks
   - `locator.fill()` for text input
   - `page.keyboard.press()` for key presses
   - `page.evaluate()` for scrolling
3. **Browser** → performs the action

### Key Components

#### 1. WebSocket Management
- **File**: `backend/websocket_manager.py`
- **Class**: `VisualWebSocketManager`
- **Current Responsibilities**:
  - Client connection lifecycle
  - Message routing (ping/pong, status, sequence_reset)
  - Event broadcasting
- **Key Method**: `_handle_client_message()` - handles incoming messages from clients

#### 2. Visual Streaming Router
- **File**: `backend/routers_visual.py`
- **WebSocket Endpoint**: `/workflows/visual/{session_id}/stream`
- **Current Message Types**:
  - `ping` → pong response
  - `client_ready` → status acknowledgment
  - `sequence_reset_request` → replay from last FullSnapshot

#### 3. Browser Factory
- **File**: `workflow_use/browser/browser_factory.py`
- **Class**: `BrowserFactory`
- **Responsibilities**:
  - Browser instance creation with profiles
  - RRWeb recorder setup
  - Session management
- **Access Point**: Browser instances are stored in `_active_sessions`

#### 4. Workflow Controller
- **File**: `workflow_use/controller/service.py`
- **Class**: `WorkflowController`
- **Current Actions**: navigation, click, input, scroll, key_press, etc.
- **Access**: Gets page via `browser_session.get_current_page()`

## Implementation Approach

### Key Design Decision: Simple Direct Handler

Based on the frontend requirements, we're using a **simple, direct approach**:
- Single WebSocket endpoint handler in `routers_visual.py`
- Direct Playwright command execution (no intermediate layers)
- Session validation via `browser_factory.get_browser_for_session()`
- Message routing in the WebSocket loop

**Why Simple?**
- Frontend already does coordinate transformation
- Frontend already does rate limiting (client-side)
- Frontend handles 5-minute timeout
- Backend just needs to validate and execute

### Message Flow

```
Client (Frontend)
  ↓ (sends: {session_id, message: {type, action, x, y, ...}})
WebSocket Endpoint /workflows/visual/{session_id}/control
  ↓ (validate session exists)
  ↓ (get page = browser_factory.get_page_for_session())
  ↓ (route by message.type: mouse/keyboard/wheel)
Playwright Page API (page.mouse.click, page.keyboard.press, etc.)
  ↓ (execute command)
  ↓ (send ack or error response)
Client (Frontend)
```

### Frontend Message Format (MUST MATCH EXACTLY)

All messages from frontend use this wrapper:
```json
{
  "session_id": "visual-57ac55f6-2387-4ac1-88b6-acc8e25a1368",
  "message": { /* actual control message */ }
}
```

#### Mouse Click Message
```json
{
  "session_id": "...",
  "message": {
    "type": "mouse",
    "action": "click",
    "x": 884,
    "y": 822,
    "button": "left",
    "clickCount": 1,
    "timestamp": 1760416949406
  }
}
```

#### Mouse Move/Down/Up Messages
```json
{
  "session_id": "...",
  "message": {
    "type": "mouse",
    "action": "move",  // or "down", "up", "dblclick"
    "x": 500,
    "y": 300,
    "button": "left",  // for down/up
    "timestamp": 1760416949500
  }
}
```

#### Wheel Message
```json
{
  "session_id": "...",
  "message": {
    "type": "wheel",
    "deltaX": 0,
    "deltaY": 100,
    "x": 500,
    "y": 300,
    "timestamp": 1760416949600
  }
}
```

#### Keyboard Messages
```json
{
  "session_id": "...",
  "message": {
    "type": "keyboard",
    "action": "down",  // or "up"
    "key": "a",
    "code": "KeyA",
    "timestamp": 1760416949406
  }
}
```

### Backend Response Format (MUST MATCH EXACTLY)

#### Connection Established (on connect)
```json
{
  "type": "connection_established",
  "session_id": "visual-57ac55f6-2387-4ac1-88b6-acc8e25a1368",
  "timestamp": 1760416949.123
}
```

#### Acknowledgment (success)
```json
{
  "type": "ack",
  "timestamp": 1760416949.456,
  "message": "Command executed successfully"
}
```

#### Error Response
```json
{
  "type": "error",
  "error_type": "invalid_message|session_not_found|browser_not_ready|execution_failed|rate_limit_exceeded",
  "error": "Detailed error message",
  "timestamp": 1760416949.456
}
```

#### Session Expired
```json
{
  "type": "session_expired",
  "message": "Control session has expired",
  "timestamp": 1760416949.456
}
```

## Implementation Details

### Single File Implementation

We'll implement everything in `backend/routers_visual.py` as a new WebSocket endpoint. No need for separate modules since the logic is straightforward.

### WebSocket Handler Structure

```python
@visual_router.websocket("/{session_id}/control")
async def control_channel_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for control channel (mouse/keyboard forwarding)"""
    
    # 1. Normalize session_id (handle with/without 'visual-' prefix)
    # 2. Validate session exists and browser is active
    # 3. Get page from browser_factory
    # 4. Send connection_established
    # 5. Message loop: receive → route → execute → send ack/error
    # 6. Handle disconnection gracefully
```

### Message Handler Functions

```python
async def handle_mouse_message(page: Page, message: dict):
    """Execute mouse actions"""
    action = message['action']
    x = message['x']
    y = message['y']
    
    if action == 'click':
        button = message.get('button', 'left')
        await page.mouse.click(x, y, button=button)
    elif action == 'move':
        await page.mouse.move(x, y)
    elif action == 'down':
        await page.mouse.move(x, y)
        await page.mouse.down(button=message.get('button', 'left'))
    elif action == 'up':
        await page.mouse.up(button=message.get('button', 'left'))
    elif action == 'dblclick':
        await page.mouse.dblclick(x, y)

async def handle_keyboard_message(page: Page, message: dict):
    """Execute keyboard actions"""
    action = message['action']
    key = message['key']
    
    if action == 'down':
        # For single chars, use press (handles down+up)
        if len(key) == 1:
            await page.keyboard.press(key)
        else:
            # For special keys (Enter, Tab, etc.)
            await page.keyboard.down(key)
    elif action == 'up':
        await page.keyboard.up(key)

async def handle_wheel_message(page: Page, message: dict):
    """Execute wheel scroll"""
    await page.mouse.wheel(message['deltaX'], message['deltaY'])
```

## Integration with Existing Code

### Getting Page from BrowserFactory

The control channel needs access to the `Page` object (via **Patchright**, not vanilla Playwright):

**Note**: The project uses **Patchright** (stealth Playwright fork) for better anti-detection.
All browser automation goes through Patchright via monkey-patching in `browser_factory.py`.

```python
from workflow_use.browser.browser_factory import browser_factory

# In the WebSocket handler
browser = await browser_factory.get_browser_for_session(session_id)
if not browser:
    # Send error: session_not_found
    
page = await browser.get_current_page()
if not page:
    # Send error: browser_not_ready
```

### Session ID Normalization

Reuse the same normalization logic as the visual streaming endpoint:

```python
original_session_id = session_id
if not session_id.startswith("visual-"):
    try:
        import uuid
        uuid.UUID(session_id)  # Validate UUID format
        session_id = f"visual-{session_id}"
        logger.info(f"Normalized session ID from '{original_session_id}' to '{session_id}'")
    except ValueError:
        # Invalid session ID format
        await websocket.send_json({
            "type": "error",
            "error_type": "invalid_message",
            "error": f"Invalid session ID format: {original_session_id}",
            "timestamp": time.time()
        })
        await websocket.close(code=4400)
        return
```

## Security & Best Practices

### 🔒 CRITICAL: RRWeb Input Masking

**Problem:** When users type via Control Channel, rrweb records the input values and replays them!

**Current Configuration** (`workflow_use/rrweb/config.py`):
```python
"maskAllInputs": False,  # ❌ Passwords will be visible in replay!
```

**Solution Options:**

#### Option 1: Mask All Inputs (Most Secure)
```python
# In workflow_use/rrweb/config.py
ESSENTIAL_OPTIONS = {
    "maskAllInputs": True,  # ✅ All inputs masked with ***
    # ... other options
}
```
**Trade-off:** All input fields show `***` in replay, including non-sensitive data

#### Option 2: Smart Masking (Recommended)
```python
# In workflow_use/rrweb/config.py
ESSENTIAL_OPTIONS = {
    "maskAllInputs": False,
    "maskInputOptions": {
        "password": True,      # ✅ Always mask password fields
        "email": False,        # Show email inputs
        "tel": False,         # Show phone inputs
        "text": False,        # Show text inputs
    },
    "maskInputFn": True,      # Enable custom masking function
    # ... other options
}
```

#### Option 3: Attribute-Based Masking (Flexible)
```python
# Any input with data-rrweb-mask attribute will be masked
# Frontend can add this to sensitive fields:
# <input type="text" data-rrweb-mask />
```


### Input Validation
- Validate coordinates are within bounds (0-10000)
- Validate `key` values are reasonable strings
- Check required fields exist in messages

### Secure Logging
**⚠️ CRITICAL**: Do NOT log sensitive keyboard input in backend

```python
# Bad - logs password
logger.info(f"Keyboard input: {message['key']}")  # ❌

# Good - only log action type  
logger.info(f"Keyboard action: {message['action']}")  # ✅
logger.info(f"Mouse click at ({x}, {y})")  # ✅
```

### Rate Limiting (Phase 2)
Backend should enforce 100 messages/second per session:
```python
# Track message timestamps per session
last_message_times = collections.deque(maxlen=100)
last_message_times.append(time.time())

if len(last_message_times) == 100:
    elapsed = time.time() - last_message_times[0]
    if elapsed < 1.0:  # 100 messages in < 1 second
        await websocket.send_json({
            "type": "error",
            "error_type": "rate_limit_exceeded",
            "error": "Too many messages per second",
            "timestamp": time.time()
        })
        continue
```

### Session Timeout (Phase 2)
Track connection time and close after 5 minutes:
```python
connection_start = time.time()
MAX_DURATION = 5 * 60  # 5 minutes

# In message loop
if time.time() - connection_start > MAX_DURATION:
    await websocket.send_json({
        "type": "session_expired",
        "message": "Control session has expired (5 minute limit)",
        "timestamp": time.time()
    })
    await websocket.close(code=4408)
    break
```

## Implementation Task List

### Phase 1: MVP (Required for Frontend Integration)

**MVP-1**: Create control channel WebSocket endpoint at `/workflows/visual/{session_id}/control` in `routers_visual.py`
- Add WebSocket route decorator
- Handle connection accept

**MVP-2**: Implement session validation logic
- Normalize session_id (handle with/without 'visual-' prefix)
- Check session exists via `browser_factory.get_browser_for_session()`
- Get Playwright Page object

**MVP-3**: Send `connection_established` message on WebSocket accept
- Include session_id and timestamp
- Match frontend expected format exactly

**MVP-4**: Implement mouse click handler
- Parse message: type='mouse', action='click', x, y, button
- Call `page.mouse.click(x, y, button=button)`
- Handle clickCount (for double-click detection)

**MVP-5**: Implement keyboard input handler
- Parse message: type='keyboard', action='down'/'up', key, code
- Use `page.keyboard.press(key)` for single characters
- Use `page.keyboard.down(key)` for special keys (Enter, Tab, etc.)

**MVP-6**: Send acknowledgment response after successful command
- Format: `{"type": "ack", "timestamp": time.time(), "message": "..."}`

**MVP-7**: Implement error handling
- Send error response with correct `error_type`:
  - `session_not_found` - session doesn't exist
  - `browser_not_ready` - page not available
  - `execution_failed` - Playwright command failed
  - `invalid_message` - malformed message

**MVP-8**: Add message validation
- Check required fields exist (type, action, x, y for mouse; type, action, key for keyboard)
- Validate message structure matches frontend spec

### Phase 2: Enhancements (Nice-to-have)

**ENHANCE-1**: Add mouse move and mouse down/up handlers
- `page.mouse.move(x, y)`
- `page.mouse.down(button=button)` + `page.mouse.up(button=button)`

**ENHANCE-2**: Add mouse wheel handler
- `page.mouse.wheel(deltaX, deltaY)`

**ENHANCE-3**: Implement rate limiting
- Track messages per second per session
- Return `rate_limit_exceeded` error if > 100 msg/sec

**ENHANCE-4**: Add input coordinate validation
- Bounds check: 0 <= x <= 10000, 0 <= y <= 10000
- Prevent invalid coordinates

**ENHANCE-5**: Implement session timeout
- Track connection start time
- Send `session_expired` after 5 minutes
- Close connection with code 4408

**ENHANCE-6**: Add secure logging
- Log session start/end
- Log errors
- **DO NOT** log keyboard input (sensitive data)
- Only log mouse click positions and special key names

### Phase 3: Testing

**TEST-1**: Write unit tests for message handlers
- Test mouse, keyboard, wheel message parsing
- Test Playwright command mapping

**TEST-2**: Manual integration testing with live frontend
- Connect control channel
- Test mouse clicks
- Test keyboard typing
- Verify browser actions execute correctly

## Quick Start Guide

### 1. Add WebSocket Endpoint
Open `backend/routers_visual.py` and add:
```python
@visual_router.websocket("/{session_id}/control")
async def control_channel_websocket(websocket: WebSocket, session_id: str):
    # Implementation here
```

### 2. Get Browser Page
```python
from workflow_use.browser.browser_factory import browser_factory

browser = await browser_factory.get_browser_for_session(session_id)
page = await browser.get_current_page()
```

### 3. Handle Messages
```python
while True:
    data = await websocket.receive_json()
    message = data.get('message', {})
    
    if message['type'] == 'mouse':
        await handle_mouse(page, message)
    elif message['type'] == 'keyboard':
        await handle_keyboard(page, message)
    
    await websocket.send_json({"type": "ack", "timestamp": time.time()})
```

## Key Differences from Visual Streaming

| Aspect | Visual Streaming | Control Channel |
|--------|-----------------|-----------------|
| **Endpoint** | `/{session_id}/stream` | `/{session_id}/control` |
| **Direction** | Server → Client | Client → Server |
| **Data** | rrweb DOM events | Mouse/keyboard commands |
| **Protocol** | Broadcast events | Request/response |
| **Manager** | RRWebEventStreamer | Direct handler |

## Summary

- **Simple direct implementation** in `routers_visual.py`
- **No complex managers** needed
- **Frontend already handles** coordinate transformation, client-side rate limiting, and 5-minute timeout
- **Backend focuses on** session validation, Playwright command execution, and error handling
- **MVP-first approach**: Get click + keyboard working first, then add enhancements

## Related Documentation

- `doc/CONTROL_CHANNEL.md` - Frontend requirements (the source of truth)
- `doc/RRWEB_ARCHITETCTURE.md` - Visual streaming architecture
- `backend/routers_visual.py` - Visual router implementation (existing streaming endpoint)

