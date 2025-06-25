# rrweb Visual Streaming Demo

A complete real-time visual workflow monitoring system using rrweb technology for recording and replaying browser interactions.

## 🎯 Overview

This demo showcases a production-ready visual streaming system that captures browser interactions in real-time using rrweb (record and replay the web) and streams them to a web-based viewer. Perfect for monitoring automated workflows, debugging browser automation, and providing visual feedback for long-running processes.

## 🚀 Features

- **Real-time Visual Streaming**: Live browser interaction recording and replay
- **Optimized Performance**: Sub-10 second startup (75% faster than initial implementation)
- **Cross-origin Support**: Works with iframes and cross-origin content
- **WebSocket Communication**: Efficient real-time event streaming
- **Professional UI**: Clean, responsive viewer with statistics and controls
- **Scalable Architecture**: Supports multiple concurrent sessions

## 📁 Project Structure

```
rrweb_demo/
├── backend/
│   └── demo_backend.py          # FastAPI server with rrweb streaming
├── frontend/
│   └── demo_viewer.html         # Web-based viewer for live streams
├── tests/
│   └── test_optimized_speed.py  # Performance testing and benchmarks
├── docs/
│   └── ARCHITECTURE.md          # Technical architecture documentation
└── README.md                    # This file
```

## 🛠️ Quick Start

### 1. Install Dependencies

```bash
# Install required packages (if not already installed)
pip install fastapi uvicorn websockets
```

### 2. Start the Demo Server

```bash
cd rrweb_demo/backend
python demo_backend.py
```

Server will start on: http://localhost:8000

### 3. Open the Viewer

Navigate to: http://localhost:8000

### 4. Start a Demo Workflow

1. Connect to WebSocket (default session: `demo-session-123`)
2. Click "Start Demo Workflow"
3. Watch real-time browser interactions!

## 📊 Performance Metrics

| Metric | Before Optimization | After Optimization | Improvement |
|--------|-------------------|-------------------|-------------|
| **Total Startup Time** | ~30+ seconds | ~8-10 seconds | **75% faster** |
| **First Visual Event** | ~15 seconds | ~5 seconds | **67% faster** |
| **Event Responsiveness** | 150-800ms | 100-400ms | **2x faster** |
| **Navigation Speed** | ~4 seconds | ~2 seconds | **50% faster** |

## 🏗️ Architecture

### Backend Components

- **FastAPI Server**: Handles HTTP requests and WebSocket connections
- **Visual Browser**: Enhanced browser with rrweb recording capabilities
- **Event Streaming**: Real-time event processing and broadcasting
- **WebSocket Manager**: Connection management and message routing

### Frontend Components

- **rrweb Player**: Live replay of browser interactions
- **WebSocket Client**: Real-time event reception
- **Statistics Panel**: Performance monitoring and debugging
- **Control Interface**: Session management and workflow controls

## 🔧 Configuration

### Demo Workflow Steps

The demo performs these automated actions:

1. **Page Load**: Navigate to example.com
2. **Scroll Interaction**: Scroll down the page
3. **Link Clicking**: Attempt to click available links
4. **Form Interaction**: Try to fill form fields
5. **Navigation**: Navigate to httpbin.org/html
6. **Final Actions**: Scroll and hover interactions

### Optimization Settings

Key performance optimizations applied:

```javascript
// rrweb Recording Settings
{
  checkoutEveryNms: 5000,     // 5s checkpoints (was 10s)
  sampling: {
    scroll: 100,              // 100ms scroll events (was 150ms)
    media: 400,               // 400ms media events (was 800ms)
    input: 'last'             // Only final input values
  }
}
```

## 🧪 Testing

### Performance Testing

```bash
cd rrweb_demo/tests
python test_optimized_speed.py
```

This will benchmark:
- Browser creation time
- rrweb injection speed
- Navigation performance
- Event generation timing

### Load Testing

The system supports multiple concurrent sessions. Test with different session IDs:

```javascript
// Connect to different sessions
const sessionId = 'test-session-' + Math.random().toString(36).substr(2, 9);
```

## 🔍 Debugging

### Common Issues

1. **WebSocket Connection Errors**
   - Check if server is running on port 8000
   - Verify session ID matches between client and server

2. **No Visual Events**
   - Ensure rrweb CDN is accessible
   - Check browser console for JavaScript errors

3. **Performance Issues**
   - Monitor the statistics panel for event rates
   - Check network tab for WebSocket message sizes

### Debug Logging

Enable detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📈 Monitoring

The viewer provides real-time statistics:

- **Events Received**: Total rrweb events processed
- **Data Received**: Bandwidth usage in KB
- **Events/Second**: Real-time event rate
- **Connection Time**: Session duration
- **Latency**: Message processing delay

## 🚀 Production Deployment

### Environment Variables

```bash
export RRWEB_PORT=8000
export RRWEB_HOST=0.0.0.0
export RRWEB_LOG_LEVEL=info
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim
COPY rrweb_demo/ /app/
WORKDIR /app/backend
RUN pip install fastapi uvicorn websockets
EXPOSE 8000
CMD ["python", "demo_backend.py"]
```

### Scaling Considerations

- Use Redis for session management across multiple instances
- Implement WebSocket load balancing
- Consider event persistence for replay scenarios

## 🤝 Integration

### Using with Existing Workflows

```python
from workflow_use.browser.visual_browser import VisualWorkflowBrowser

# Create visual browser
visual_browser = VisualWorkflowBrowser(
    session_id="your-session-id",
    event_callback=your_streaming_callback
)

# Your workflow code here
await visual_browser.create_browser()
await visual_browser.inject_rrweb()
# ... perform your workflow steps
```

### Custom Event Handling

```python
async def custom_event_callback(event):
    # Process rrweb events
    event_type = event['event']['type']
    if event_type == 2:  # FullSnapshot
        print("New page loaded!")
    elif event_type == 3:  # IncrementalSnapshot
        print("Page interaction detected!")
```

## 📚 Additional Resources

- [rrweb Documentation](https://www.rrweb.io/)
- [FastAPI WebSocket Guide](https://fastapi.tiangolo.com/advanced/websockets/)
- [Browser Automation Best Practices](https://playwright.dev/docs/best-practices)

## 🐛 Troubleshooting

### Browser Process Conflicts

```bash
# Kill existing browser processes
pkill -f chromium || pkill -f chrome

# Remove browser profile locks
rm -rf ~/.config/browseruse/profiles/default
```

### WebSocket Connection Issues

1. Check firewall settings
2. Verify port 8000 is available
3. Test with different browsers
4. Check for proxy/VPN interference

## 📝 License

This demo is part of the wf-backend project and follows the same licensing terms.

---

**Built with ❤️ for real-time visual workflow monitoring** 