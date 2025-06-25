"""
rrweb Event Streaming System

This module handles the capture, processing, and streaming of rrweb events
for real-time visual workflow feedback.
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass
from enum import Enum
import orjson  # Fast JSON serialization

logger = logging.getLogger(__name__)


class StreamingPhase(Enum):
    """Explicit phases of visual streaming lifecycle"""
    SETUP = "setup"           # Browser creation, rrweb injection
    READY = "ready"           # rrweb recording, waiting for workflow
    EXECUTING = "executing"   # Workflow execution in progress
    COMPLETED = "completed"   # Workflow finished
    CLEANUP = "cleanup"       # Browser cleanup


@dataclass
class RRWebEvent:
    """Structured rrweb event with metadata"""
    session_id: str
    timestamp: float
    event_type: int
    event_data: Dict[str, Any]
    sequence_id: int = 0
    phase: StreamingPhase = StreamingPhase.SETUP  # Track which phase this event belongs to
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'session_id': self.session_id,
            'timestamp': self.timestamp,
            'event_type': self.event_type,
            'event_data': self.event_data,
            'sequence_id': self.sequence_id,
            'phase': self.phase.value
        }
    
    def to_json(self) -> bytes:
        """Fast JSON serialization using orjson"""
        return orjson.dumps(self.to_dict())


class RRWebEventStreamer:
    """Manages rrweb event capture, processing, and streaming"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.event_buffer = deque(maxlen=1000)  # Recent events buffer
        self.event_queue = asyncio.Queue()
        self.sequence_counter = 0
        self.connected_clients: Set[Any] = set()  # WebSocket connections
        self.streaming_active = False
        
        # Phase management - explicit instead of guessing
        self.current_phase = StreamingPhase.SETUP
        self.phase_transitions = []  # Track phase changes with timestamps
        
        # Browser readiness tracking
        self.browser_ready = False  # Track if browser automation has started
        self.browser_ready_time = None  # When browser became ready
        self.first_workflow_event_received = False  # Track first workflow event
        
        # Statistics
        self.stats = {
            'total_events': 0,
            'workflow_events': 0,  # Only events during EXECUTING phase
            'setup_events': 0,     # Events during SETUP/READY phases
            'events_per_second': 0,
            'last_event_time': 0,
            'buffer_size': 0,
            'connected_clients': 0,
            'browser_ready': False,
            'browser_ready_time': None,
            'first_workflow_event_time': None,
            'phase_transitions': []
        }
        
        # Performance monitoring
        self._last_stats_update = time.time()
        self._events_in_last_second = 0
    
    async def process_rrweb_event(self, event_data: Dict[str, Any]) -> bool:
        """Process incoming rrweb event and prepare for streaming"""
        try:
            current_time = time.time()
            
            # Create structured event with current phase
            rrweb_event = RRWebEvent(
                session_id=self.session_id,
                timestamp=current_time,
                event_type=event_data.get('type', 0),
                event_data=event_data,
                sequence_id=self._get_next_sequence_id(),
                phase=self.current_phase  # Tag event with current phase
            )
            
            # Add to buffer (always, for replay purposes)
            self.event_buffer.append(rrweb_event)
            
            # Add to processing queue (always, for streaming)
            await self.event_queue.put(rrweb_event)
            
            # Update statistics based on phase
            self._update_stats()
            
            # Only count events during EXECUTING phase as workflow events
            if self.current_phase == StreamingPhase.EXECUTING:
                self.stats['workflow_events'] += 1
                
                if not self.first_workflow_event_received:
                    self.first_workflow_event_received = True
                    self.stats['first_workflow_event_time'] = current_time
                    self.stats['phase_transitions'].append({
                        'milestone': 'first_workflow_event',
                        'timestamp': current_time,
                        'event_type': rrweb_event.event_type,
                        'phase': self.current_phase.value
                    })
                    logger.info(f"✅ First WORKFLOW event received for session {self.session_id} (type: {rrweb_event.event_type})")
                
                logger.debug(f"Processed workflow event {rrweb_event.sequence_id} for session {self.session_id}")
            else:
                self.stats['setup_events'] += 1
                logger.debug(f"Processed setup event {rrweb_event.sequence_id} for session {self.session_id} (phase: {self.current_phase.value})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing rrweb event: {e}")
            return False
    
    async def broadcast_event(self, event: RRWebEvent) -> int:
        """Broadcast event to all connected clients"""
        if not self.connected_clients:
            return 0
        
        try:
            # Format event for frontend consumption
            frontend_event = {
                'type': 'rrweb_event',
                'session_id': event.session_id,
                'timestamp': event.timestamp,
                'event_data': event.event_data,  # This is the actual rrweb event
                'sequence_id': event.sequence_id
            }
            
            # Serialize event
            event_json = orjson.dumps(frontend_event)
            
            # Broadcast to all connected clients
            disconnected_clients = set()
            successful_sends = 0
            
            for client in self.connected_clients:
                try:
                    # Send as text, not bytes, for WebSocket compatibility
                    await client.send_text(event_json.decode('utf-8'))
                    successful_sends += 1
                except Exception as e:
                    logger.warning(f"Failed to send to client: {e}")
                    disconnected_clients.add(client)
            
            # Remove disconnected clients
            self.connected_clients -= disconnected_clients
            
            logger.debug(f"Broadcasted event to {successful_sends} clients")
            return successful_sends
            
        except Exception as e:
            logger.error(f"Error broadcasting event: {e}")
            return 0
    
    async def add_client(self, websocket) -> bool:
        """Add a new client for event streaming"""
        try:
            self.connected_clients.add(websocket)
            
            # Send buffered events to new client for catch-up
            await self._send_buffered_events(websocket)
            
            logger.info(f"Added client to session {self.session_id}. Total clients: {len(self.connected_clients)}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding client: {e}")
            return False
    
    async def remove_client(self, websocket) -> bool:
        """Remove a client from event streaming"""
        try:
            self.connected_clients.discard(websocket)
            logger.info(f"Removed client from session {self.session_id}. Total clients: {len(self.connected_clients)}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing client: {e}")
            return False
    
    async def _send_buffered_events(self, websocket) -> bool:
        """Send all buffered events to a new client"""
        try:
            for event in self.event_buffer:
                # Format event for frontend consumption
                frontend_event = {
                    'type': 'rrweb_event',
                    'session_id': event.session_id,
                    'timestamp': event.timestamp,
                    'event_data': event.event_data,  # This is the actual rrweb event
                    'sequence_id': event.sequence_id
                }
                
                event_json = orjson.dumps(frontend_event)
                await websocket.send_text(event_json.decode('utf-8'))
            
            logger.debug(f"Sent {len(self.event_buffer)} buffered events to new client")
            return True
            
        except Exception as e:
            logger.error(f"Error sending buffered events: {e}")
            return False
    
    async def start_streaming(self) -> bool:
        """Start the event streaming process"""
        if self.streaming_active:
            return True
        
        self.streaming_active = True
        
        # Start background task for processing events
        asyncio.create_task(self._event_processing_loop())
        
        logger.info(f"Started event streaming for session {self.session_id}")
        return True
    
    async def stop_streaming(self) -> bool:
        """Stop the event streaming process"""
        self.streaming_active = False
        
        # Disconnect all clients
        for client in list(self.connected_clients):
            try:
                await client.close()
            except:
                pass
        
        self.connected_clients.clear()
        
        logger.info(f"Stopped event streaming for session {self.session_id}")
        return True
    
    async def graceful_shutdown(self) -> bool:
        """Gracefully shutdown streaming by sending completion message to clients first"""
        try:
            # Send workflow completion message to all clients
            completion_message = {
                'type': 'workflow_completed',
                'session_id': self.session_id,
                'timestamp': time.time(),
                'message': 'Workflow execution completed successfully',
                'final_stats': {
                    'total_events': self.stats['total_events'],
                    'session_duration': time.time() - (self.browser_ready_time or time.time()),
                    'events_per_second': self.stats['events_per_second']
                }
            }
            
            # Broadcast completion message to all clients
            completion_json = orjson.dumps(completion_message)
            successful_sends = 0
            
            for client in list(self.connected_clients):
                try:
                    await client.send_text(completion_json.decode('utf-8'))
                    successful_sends += 1
                except Exception as e:
                    logger.warning(f"Failed to send completion message to client: {e}")
            
            logger.info(f"Sent completion message to {successful_sends} clients")
            
            # Give clients time to process the completion message
            if successful_sends > 0:
                await asyncio.sleep(2)  # 2 seconds for clients to handle completion
            
            # Now stop streaming normally
            return await self.stop_streaming()
            
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
            # Fallback to normal stop
            return await self.stop_streaming()
    
    async def _event_processing_loop(self) -> None:
        """Background loop for processing and broadcasting events"""
        while self.streaming_active:
            try:
                # Wait for event with timeout
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                
                # Broadcast to clients
                await self.broadcast_event(event)
                
            except asyncio.TimeoutError:
                # No events to process, continue
                continue
            except Exception as e:
                logger.error(f"Error in event processing loop: {e}")
                await asyncio.sleep(0.1)  # Brief pause before retrying
    
    def _get_next_sequence_id(self) -> int:
        """Get next sequence ID for event ordering"""
        self.sequence_counter += 1
        return self.sequence_counter
    
    def _update_stats(self) -> None:
        """Update performance statistics"""
        current_time = time.time()
        
        self.stats['total_events'] += 1
        self.stats['last_event_time'] = int(current_time)
        self.stats['buffer_size'] = len(self.event_buffer)
        self.stats['connected_clients'] = len(self.connected_clients)
        
        # Update events per second
        self._events_in_last_second += 1
        if current_time - self._last_stats_update >= 1.0:
            self.stats['events_per_second'] = self._events_in_last_second
            self._events_in_last_second = 0
            self._last_stats_update = current_time
    
    def get_buffered_events(self) -> List[Dict[str, Any]]:
        """Get all buffered events as dictionaries"""
        return [event.to_dict() for event in self.event_buffer]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current streaming statistics with phase information"""
        return {
            'session_id': self.session_id,
            'streaming_active': self.streaming_active,
            'browser_ready': self.browser_ready,
            'current_phase': self.current_phase.value,  # Current phase
            'truly_ready': self.is_truly_ready(),
            **self.stats
        }
    
    def clear_buffer(self) -> None:
        """Clear the event buffer"""
        self.event_buffer.clear()
        logger.info(f"Cleared event buffer for session {self.session_id}")
    
    # Browser readiness tracking methods
    async def mark_browser_ready(self) -> bool:
        """Mark that browser automation has started"""
        if not self.browser_ready:
            self.browser_ready = True
            self.browser_ready_time = time.time()
            
            # Update stats
            self.stats['browser_ready'] = True
            self.stats['browser_ready_time'] = self.browser_ready_time
            self.stats['phase_transitions'].append({
                'milestone': 'browser_ready',
                'timestamp': self.browser_ready_time
            })
            
            logger.info(f"Browser marked as ready for session {self.session_id}")
            return True
        return False
    
    async def mark_browser_not_ready(self) -> bool:
        """Mark that browser automation has stopped"""
        if self.browser_ready:
            self.browser_ready = False
            self.browser_ready_time = None
            
            # Update stats
            self.stats['browser_ready'] = False
            self.stats['browser_ready_time'] = None
            self.stats['phase_transitions'].append({
                'milestone': 'browser_not_ready',
                'timestamp': time.time()
            })
            
            logger.info(f"Browser marked as not ready for session {self.session_id}")
            return True
        return False
    
    def is_truly_ready(self) -> bool:
        """Check if streaming is truly ready for workflow events"""
        return (self.streaming_active and 
                self.current_phase == StreamingPhase.EXECUTING and
                self.browser_ready)
    
    def get_readiness_summary(self) -> Dict[str, Any]:
        """Get a summary of streaming readiness status"""
        return {
            'session_id': self.session_id,
            'streaming_active': self.streaming_active,
            'browser_ready': self.browser_ready,
            'current_phase': self.current_phase.value,
            'truly_ready': self.is_truly_ready(),
            'total_events': self.stats['total_events'],
            'workflow_events': self.stats['workflow_events'],
            'setup_events': self.stats['setup_events'],
            'first_workflow_event_received': self.first_workflow_event_received,
            'phase_transitions': self.stats['phase_transitions'],
            'browser_ready_time': self.browser_ready_time,
            'first_workflow_event_time': self.stats.get('first_workflow_event_time')
        }

    # Phase transition methods - explicit and robust
    async def transition_to_ready(self) -> bool:
        """Transition from SETUP to READY phase (rrweb recording started)"""
        if self.current_phase == StreamingPhase.SETUP:
            self.current_phase = StreamingPhase.READY
            transition_time = time.time()
            self.phase_transitions.append({
                'from_phase': StreamingPhase.SETUP.value,
                'to_phase': StreamingPhase.READY.value,
                'timestamp': transition_time
            })
            self.stats['phase_transitions'].append({
                'milestone': 'ready_phase',
                'timestamp': transition_time
            })
            logger.info(f"🔄 Phase transition: SETUP → READY for session {self.session_id}")
            return True
        return False
    
    async def transition_to_executing(self) -> bool:
        """Transition to EXECUTING phase (workflow execution started)"""
        if self.current_phase in [StreamingPhase.SETUP, StreamingPhase.READY]:
            # 🔧 CRITICAL FIX: Capture original phase before changing it
            original_phase = self.current_phase
            self.current_phase = StreamingPhase.EXECUTING
            transition_time = time.time()
            self.phase_transitions.append({
                'from_phase': original_phase.value,  # Use original phase, not current
                'to_phase': StreamingPhase.EXECUTING.value,
                'timestamp': transition_time
            })
            self.stats['phase_transitions'].append({
                'milestone': 'executing_phase',
                'timestamp': transition_time
            })
            
            # 🔧 FORCE browser ready status (for debugging)
            self.browser_ready = True
            self.browser_ready_time = time.time()
            self.stats['browser_ready'] = True
            self.stats['browser_ready_time'] = self.browser_ready_time
            logger.info(f"🔧 FORCED browser ready status for session {self.session_id}")
            
            logger.info(f"🔄 Phase transition: {original_phase.value} → EXECUTING for session {self.session_id}")
            return True
        return False
    
    async def transition_to_completed(self) -> bool:
        """Transition to COMPLETED phase (workflow execution finished)"""
        if self.current_phase == StreamingPhase.EXECUTING:
            self.current_phase = StreamingPhase.COMPLETED
            transition_time = time.time()
            self.phase_transitions.append({
                'from_phase': StreamingPhase.EXECUTING.value,
                'to_phase': StreamingPhase.COMPLETED.value,
                'timestamp': transition_time
            })
            self.stats['phase_transitions'].append({
                'milestone': 'completed_phase',
                'timestamp': transition_time
            })
            logger.info(f"🔄 Phase transition: EXECUTING → COMPLETED for session {self.session_id}")
            return True
        return False
    
    async def transition_to_cleanup(self) -> bool:
        """Transition to CLEANUP phase (browser cleanup started)"""
        if self.current_phase in [StreamingPhase.COMPLETED, StreamingPhase.EXECUTING]:
            self.current_phase = StreamingPhase.CLEANUP
            transition_time = time.time()
            self.phase_transitions.append({
                'from_phase': self.current_phase.value,
                'to_phase': StreamingPhase.CLEANUP.value,
                'timestamp': transition_time
            })
            self.stats['phase_transitions'].append({
                'milestone': 'cleanup_phase',
                'timestamp': transition_time
            })
            
            # 🔧 FIX: Don't immediately mark browser as not ready
            # The browser should stay "ready" until actual cleanup happens
            # This allows frontend to properly detect that the workflow was successful
            logger.info(f"🔄 Phase transition: {self.current_phase.value} → CLEANUP for session {self.session_id}")
            logger.info(f"🔧 Browser ready status preserved during cleanup transition for session {self.session_id}")
            return True
        return False
    
    async def final_cleanup(self) -> bool:
        """Final cleanup - call this when actually destroying the session"""
        # Mark browser as not ready when doing final cleanup
        if self.browser_ready:
            await self.mark_browser_not_ready()
            logger.info(f"🔧 Browser marked as not ready during final cleanup for session {self.session_id}")
        return True


class VisualStreamingManager:
    """Manages multiple rrweb event streamers for different sessions"""
    
    def __init__(self):
        self.streamers: Dict[str, RRWebEventStreamer] = {}
        self.cleanup_interval = 300  # 5 minutes
        self._cleanup_task_started = False
    
    def get_or_create_streamer(self, session_id: str) -> RRWebEventStreamer:
        """Get existing streamer or create new one"""
        # Start cleanup task if not already started
        if not self._cleanup_task_started:
            try:
                asyncio.create_task(self._cleanup_inactive_sessions())
                self._cleanup_task_started = True
            except RuntimeError:
                # No event loop running, will start later
                pass
        
        if session_id not in self.streamers:
            self.streamers[session_id] = RRWebEventStreamer(session_id)
            logger.info(f"Created new streamer for session {session_id}")
        
        return self.streamers[session_id]
    
    def get_streamer(self, session_id: str) -> Optional[RRWebEventStreamer]:
        """Get existing streamer"""
        return self.streamers.get(session_id)
    
    async def remove_streamer(self, session_id: str) -> bool:
        """Remove and cleanup streamer"""
        if session_id in self.streamers:
            streamer = self.streamers[session_id]
            await streamer.stop_streaming()
            del self.streamers[session_id]
            logger.info(f"Removed streamer for session {session_id}")
            return True
        return False
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all active streamers"""
        return {
            'total_sessions': len(self.streamers),
            'sessions': {
                session_id: streamer.get_stats()
                for session_id, streamer in self.streamers.items()
            }
        }
    
    async def _cleanup_inactive_sessions(self) -> None:
        """Periodically cleanup inactive sessions"""
        while True:
            try:
                current_time = time.time()
                inactive_sessions = []
                
                for session_id, streamer in self.streamers.items():
                    # Remove sessions with no clients and no recent activity
                    if (len(streamer.connected_clients) == 0 and 
                        current_time - streamer.stats['last_event_time'] > self.cleanup_interval):
                        inactive_sessions.append(session_id)
                
                # Cleanup inactive sessions
                for session_id in inactive_sessions:
                    await self.remove_streamer(session_id)
                
                await asyncio.sleep(self.cleanup_interval)
                
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)  # Wait before retrying


# Global streaming manager instance
streaming_manager = VisualStreamingManager() 