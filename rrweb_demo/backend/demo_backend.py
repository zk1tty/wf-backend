"""
Demo Backend for rrweb Visual Streaming

This is a simple FastAPI server to test the rrweb streaming infrastructure
with real-time visual workflow demonstration.
"""

import asyncio
import logging
import time
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uvicorn

# Import our infrastructure
from workflow_use.browser.visual_browser import VisualWorkflowBrowser
from backend.visual_streaming import streaming_manager
from backend.websocket_manager import websocket_manager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="rrweb Visual Streaming Demo", version="1.0.0")

# Request/Response models
class DemoStartRequest(BaseModel):
    session_id: str
    target_url: str = "https://example.com"
    workflow_steps: int = 5

class DemoStatusResponse(BaseModel):
    session_id: str
    status: str
    message: str
    active_workflows: int
    connected_clients: int

# Global state
active_demos: Dict[str, VisualWorkflowBrowser] = {}


@app.get("/")
async def root():
    """Serve the demo viewer HTML"""
    return FileResponse("demo_viewer.html")


@app.get("/demo/viewer")
async def demo_viewer():
    """Alternative endpoint for the demo viewer"""
    return FileResponse("demo_viewer.html")


@app.websocket("/demo/stream")
async def demo_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for demo streaming"""
    # Extract session_id from query params
    session_id = websocket.query_params.get("session_id", "demo-session-123")
    
    logger.info(f"Demo WebSocket connection attempt for session: {session_id}")
    
    try:
        # Handle connection through our WebSocket manager
        client_id = await websocket_manager.handle_client_connection(websocket, session_id)
        
        # Run the WebSocket message loop
        await websocket_manager.handle_websocket_loop(websocket, client_id)
        
    except WebSocketDisconnect:
        logger.info(f"Demo WebSocket disconnected for session: {session_id}")
    except Exception as e:
        logger.error(f"Demo WebSocket error for session {session_id}: {e}")


@app.post("/demo/start")
async def start_demo_workflow(request: DemoStartRequest):
    """Start a demo workflow with visual streaming"""
    session_id = request.session_id
    
    if session_id in active_demos:
        raise HTTPException(status_code=400, detail="Demo already running for this session")
    
    try:
        logger.info(f"Starting demo workflow for session: {session_id}")
        
        # Create visual browser
        visual_browser = VisualWorkflowBrowser(
            session_id=session_id,
            event_callback=create_streaming_callback(session_id)
        )
        
        # Store in active demos
        active_demos[session_id] = visual_browser
        
        # Start the demo workflow in background
        asyncio.create_task(run_demo_workflow(visual_browser, request))
        
        return {
            "session_id": session_id,
            "status": "started",
            "message": "Demo workflow started successfully",
            "websocket_url": f"ws://localhost:8000/demo/stream?session_id={session_id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to start demo workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/demo/status/{session_id}")
async def get_demo_status(session_id: str):
    """Get status of a demo workflow"""
    
    # Get WebSocket manager stats
    ws_stats = websocket_manager.get_all_stats()
    
    # Get streaming manager stats
    streaming_stats = streaming_manager.get_all_stats()
    
    # Check if demo is active
    is_active = session_id in active_demos
    
    return DemoStatusResponse(
        session_id=session_id,
        status="active" if is_active else "inactive",
        message=f"Demo is {'running' if is_active else 'not running'}",
        active_workflows=len(active_demos),
        connected_clients=ws_stats.get('websocket_stats', {}).get('active_connections', 0)
    )


@app.post("/demo/stop/{session_id}")
async def stop_demo_workflow(session_id: str):
    """Stop a demo workflow"""
    if session_id not in active_demos:
        raise HTTPException(status_code=404, detail="Demo not found")
    
    try:
        visual_browser = active_demos[session_id]
        await visual_browser.cleanup()
        del active_demos[session_id]
        
        # Clean up streaming
        await streaming_manager.remove_streamer(session_id)
        
        logger.info(f"Demo workflow stopped for session: {session_id}")
        
        return {
            "session_id": session_id,
            "status": "stopped",
            "message": "Demo workflow stopped successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to stop demo workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/demo/stats")
async def get_demo_stats():
    """Get comprehensive demo statistics"""
    return {
        "active_demos": len(active_demos),
        "demo_sessions": list(active_demos.keys()),
        "websocket_stats": websocket_manager.get_all_stats(),
        "streaming_stats": streaming_manager.get_all_stats()
    }


def create_streaming_callback(session_id: str):
    """Create event callback that feeds into streaming system"""
    async def streaming_callback(event: Dict[str, Any]) -> None:
        try:
            streamer = streaming_manager.get_or_create_streamer(session_id)
            await streamer.process_rrweb_event(event.get('event', {}))
        except Exception as e:
            logger.error(f"Error in streaming callback for {session_id}: {e}")
    
    return streaming_callback


async def run_demo_workflow(visual_browser: VisualWorkflowBrowser, request: DemoStartRequest):
    """Run a demo workflow with visual feedback - OPTIMIZED FOR SPEED"""
    session_id = request.session_id
    
    try:
        logger.info(f"Creating browser for demo session: {session_id}")
        
        # Create browser (non-headless for visual demo) - this now handles initial navigation
        browser = await visual_browser.create_browser(headless=False)
        
        # Navigate to target URL if different from what browser creation navigated to
        current_url = visual_browser.page.url if visual_browser.page else "about:blank"
        if request.target_url != current_url and not current_url.startswith(request.target_url):
            logger.info(f"Navigating to target URL {request.target_url} for session: {session_id}")
            await visual_browser.navigate_to(request.target_url)
            await asyncio.sleep(1)  # REDUCED: Wait for page to load (was 3s)
        
        # Inject rrweb - page should already be on a real URL
        logger.info(f"Injecting rrweb for session: {session_id}")
        injection_success = await visual_browser.inject_rrweb()
        
        if not injection_success:
            logger.error(f"Failed to inject rrweb for session: {session_id}")
            return
        
        # Start recording
        await visual_browser.start_recording()
        
        # REDUCED: Wait for recording to stabilize (was 2s)
        await asyncio.sleep(0.5)
        
        # Perform demo workflow steps with enhanced activity - OPTIMIZED TIMING
        for step in range(request.workflow_steps):
            logger.info(f"Demo step {step + 1}/{request.workflow_steps} for session: {session_id}")
            
            # Simulate workflow actions
            await simulate_workflow_step(visual_browser, step)
            
            # Add some micro-interactions to generate more events
            await generate_micro_interactions(visual_browser)
            
            # REDUCED: Wait between steps (was 3s)
            await asyncio.sleep(1)  # Much faster demo execution
        
        logger.info(f"Demo workflow completed for session: {session_id}")
        
        # Keep browser alive for extended viewing
        logger.info(f"Keeping browser alive for extended viewing - session: {session_id}")
        
        # Instead of sleep, keep checking if clients are connected
        for _ in range(60):  # Check for 5 minutes (60 * 5 seconds)
            await asyncio.sleep(5)
            
            # Check if we still have connected clients
            streamer = streaming_manager.get_streamer(session_id)
            if streamer and len(streamer.connected_clients) > 0:
                logger.debug(f"Session {session_id} has {len(streamer.connected_clients)} connected clients")
            elif streamer and len(streamer.connected_clients) == 0:
                logger.info(f"No clients connected to session {session_id}, will cleanup soon")
                break
        
    except Exception as e:
        logger.error(f"Demo workflow error for session {session_id}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
    
    finally:
        # Cleanup with better error handling
        try:
            logger.info(f"Starting cleanup for session: {session_id}")
            
            # Stop recording first
            if visual_browser.recording_active:
                await visual_browser.stop_recording()
            
            # Clean up browser
            await visual_browser.cleanup()
            
            # Remove from active demos
            if session_id in active_demos:
                del active_demos[session_id]
                
            logger.info(f"Cleanup completed for session: {session_id}")
            
        except Exception as e:
            logger.error(f"Cleanup error for session {session_id}: {e}")


async def simulate_workflow_step(visual_browser: VisualWorkflowBrowser, step: int):
    """Simulate different workflow steps - OPTIMIZED FOR SPEED"""
    page = visual_browser.page
    
    if not page:
        return
    
    try:
        if step == 0:
            # Scroll down
            await page.evaluate("window.scrollTo(0, 200)")
            
        elif step == 1:
            # Click on a link if available
            try:
                await page.click('a', timeout=1000)  # REDUCED timeout (was 2000ms)
            except:
                # If no link, just scroll more
                await page.evaluate("window.scrollTo(0, 400)")
                
        elif step == 2:
            # Try to interact with form elements
            try:
                await page.fill('input[type="text"]', 'demo text', timeout=1000)  # REDUCED timeout
            except:
                await page.evaluate("window.scrollTo(0, 600)")
                
        elif step == 3:
            # Navigate to a different page and re-inject rrweb
            await page.goto("https://httpbin.org/html")
            await asyncio.sleep(1)  # REDUCED: Wait for page load (was 2s)
            
            # Re-inject rrweb after navigation to capture new page
            logger.info(f"Re-injecting rrweb after navigation for session: {visual_browser.session_id}")
            await visual_browser.inject_rrweb()
            await asyncio.sleep(0.5)  # REDUCED: Wait for rrweb to initialize (was 1s)
            
        elif step == 4:
            # Final scroll and hover
            await page.evaluate("window.scrollTo(0, 0)")
            try:
                await page.hover('body')
            except:
                pass
                
    except Exception as e:
        logger.warning(f"Workflow step {step} failed: {e}")


async def generate_micro_interactions(visual_browser: VisualWorkflowBrowser):
    """Generate small interactions to produce more rrweb events - OPTIMIZED"""
    page = visual_browser.page
    
    if not page:
        return
    
    try:
        # Small mouse movements and clicks to generate events - FASTER
        await page.mouse.move(100, 100)
        await asyncio.sleep(0.1)  # REDUCED (was 0.2s)
        await page.mouse.move(150, 150)
        await asyncio.sleep(0.1)  # REDUCED (was 0.2s)
        
        # Small scroll movements
        await page.evaluate("window.scrollBy(0, 50)")
        await asyncio.sleep(0.15)  # REDUCED (was 0.3s)
        await page.evaluate("window.scrollBy(0, -50)")
        
        # Try to hover over elements
        try:
            await page.hover('body', timeout=500)  # REDUCED timeout (was 1000ms)
        except:
            pass
            
    except Exception as e:
        logger.debug(f"Micro-interaction failed: {e}")


if __name__ == "__main__":
    logger.info("🚀 Starting rrweb Visual Streaming Demo Server")
    logger.info("📱 Demo viewer available at: http://localhost:8000")
    logger.info("🔌 WebSocket endpoint: ws://localhost:8000/demo/stream")
    
    uvicorn.run(
        "demo_backend:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable reload for demo
        log_level="info"
    ) 