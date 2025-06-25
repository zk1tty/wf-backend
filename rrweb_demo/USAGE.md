# rrweb Demo Usage Guide

## Quick Start (3 Steps)

### 1. Launch the Demo
```bash
cd rrweb_demo
python start_demo.py
```

### 2. Open Your Browser
Navigate to: **http://localhost:8000**

### 3. Start Streaming
1. Click "Connect to Stream" (uses default session: `demo-session-123`)
2. Click "Start Demo Workflow"
3. Watch the magic happen! ✨

## What You'll See

The demo performs these actions in real-time:

1. **🌐 Browser Launch**: Creates a new browser instance
2. **📝 Page Load**: Navigates to example.com
3. **🖱️ Interactions**: Scrolls, clicks, and hovers
4. **🔄 Navigation**: Moves to httpbin.org/html
5. **👀 Live Replay**: All actions streamed to your viewer

## Performance Expectations

- **First events appear**: ~5 seconds (was 30+ seconds!)
- **Total demo duration**: ~8-10 seconds
- **Event responsiveness**: 100-400ms
- **75% faster** than original implementation

## Customization

Edit `config.py` to customize:
- Demo workflow steps
- Timing delays
- Browser settings
- rrweb recording options

## Troubleshooting

### No Events Appearing?
1. Check browser console for errors
2. Verify WebSocket connection (green status)
3. Ensure no firewall blocking port 8000

### Browser Won't Start?
```bash
# Kill any existing browser processes
pkill -f chromium || pkill -f chrome

# Remove browser profile locks
rm -rf ~/.config/browseruse/profiles/default
```

### Still Having Issues?
Check the detailed troubleshooting in `README.md`

## Advanced Usage

### Multiple Sessions
```javascript
// Use different session IDs for concurrent streams
const sessionId = 'my-custom-session-' + Date.now();
```

### Performance Testing
```bash
cd tests
python test_optimized_speed.py
```

### Production Deployment
```bash
export RRWEB_ENV=production
export RRWEB_HOST=0.0.0.0
export RRWEB_PORT=8000
python start_demo.py
```

---

**That's it! Enjoy your optimized visual workflow streaming! 🚀** 