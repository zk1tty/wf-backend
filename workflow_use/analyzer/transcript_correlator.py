"""
Transcript Correlator Service

This service correlates voice transcripts with workflow steps to:
1. Add voiceContext to each step showing what the user was saying
2. Clarify user intent for each action
3. Enable optimization by comparing voice intent vs actual actions
4. Detect mismatches between spoken intent and recorded action
"""

import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class VoiceContext:
    """Voice context for a workflow step"""
    
    def __init__(
        self,
        relevant_text: str,
        transcript_index_start: int,
        transcript_index_end: int,
        time_offset_ms: int,
        confidence: float,
        entries: List[Dict[str, Any]]
    ):
        self.relevant_text = relevant_text
        self.transcript_index_start = transcript_index_start
        self.transcript_index_end = transcript_index_end
        self.time_offset_ms = time_offset_ms  # How far before/after the action
        self.confidence = confidence  # 0.0 to 1.0
        self.entries = entries  # Raw transcript entries
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage in workflow step"""
        return {
            'relevantText': self.relevant_text,
            'transcriptIndexStart': self.transcript_index_start,
            'transcriptIndexEnd': self.transcript_index_end,
            'timeOffsetMs': self.time_offset_ms,
            'confidence': self.confidence,
            'entries': self.entries
        }


class TranscriptCorrelator:
    """
    Correlates voice transcripts with workflow steps using timestamp analysis.
    
    This implements Option 3 (Hybrid Approach) from the integration plan:
    - Stores full transcript separately
    - Adds voiceContext to each workflow step
    """
    
    def __init__(
        self,
        time_window_before_ms: int = 2000,   # Look 2s before action (reduced from 5s)
        time_window_after_ms: int = 1500,    # Look 1.5s after action (reduced from 3s)
        min_confidence: float = 0.5,         # Minimum confidence (increased from 0.3)
        transcript_delay_ms: int = 750,      # Account for 500-1000ms transcript delay
        prefer_closest: bool = True          # Only match closest transcript entry
    ):
        """
        Initialize the transcript correlator.
        
        Args:
            time_window_before_ms: How far to look before the action (ms)
            time_window_after_ms: How far to look after the action (ms)
            min_confidence: Minimum confidence score to include a match
            transcript_delay_ms: Expected delay in transcript recording (500-1000ms typical)
            prefer_closest: If True, only match the closest transcript entry (reduces false matches)
        """
        self.time_window_before_ms = time_window_before_ms
        self.time_window_after_ms = time_window_after_ms
        self.min_confidence = min_confidence
        self.transcript_delay_ms = transcript_delay_ms
        self.prefer_closest = prefer_closest
        
        logger.info(
            f"TranscriptCorrelator initialized with time windows: "
            f"before={time_window_before_ms}ms, after={time_window_after_ms}ms, "
            f"transcript_delay={transcript_delay_ms}ms, min_confidence={min_confidence:.2f}, "
            f"prefer_closest={prefer_closest}"
        )
    
    def correlate_workflow(
        self,
        workflow_data: Dict[str, Any],
        transcript_data: Dict[str, Any],
        use_segments: bool = True
    ) -> Dict[str, Any]:
        """
        Add voiceContext to all steps in a workflow.
        
        Args:
            workflow_data: Workflow JSON with steps
            transcript_data: Transcript with entries and startedAtMs
            use_segments: If True, use segment-based correlation (recommended).
                         If False, use time-window based correlation (legacy).
        
        Returns:
            Enhanced workflow with voiceContext added to each step
        """
        if not transcript_data or not transcript_data.get('entries'):
            logger.warning("No transcript data provided, returning workflow unchanged")
            return workflow_data
        
        recording_start = transcript_data.get('startedAtMs')
        if recording_start is None:
            logger.warning("No startedAtMs in transcript, cannot correlate timestamps")
            return workflow_data
        
        entries = transcript_data['entries']
        steps = workflow_data.get('steps', [])
        
        logger.info(
            f"Correlating {len(entries)} transcript entries with {len(steps)} workflow steps "
            f"using {'segment-based' if use_segments else 'time-window'} approach"
        )
        
        # Choose correlation method
        if use_segments:
            steps_with_context = self._correlate_by_segments(steps, entries, recording_start)
        else:
            steps_with_context = self._correlate_by_time_windows(steps, entries, recording_start)
        
        logger.info(
            f"Correlation complete: {steps_with_context}/{len(steps)} steps "
            f"have voice context"
        )
        
        return workflow_data
    
    def _correlate_by_segments(
        self,
        steps: List[Dict[str, Any]],
        entries: List[Dict[str, Any]],
        recording_start: int
    ) -> int:
        """
        Segment-based correlation: Each voice command applies to all actions
        until the next voice command.
        
        This matches real user behavior:
        1. User speaks: "Go to Product Hunt"
        2. User performs multiple actions silently
        3. User speaks again: "Copy the name" ← NEW SEGMENT
        4. More actions...
        
        Returns:
            Number of steps with voice context added
        """
        steps_with_context = 0
        
        # Adjust transcript timestamps for recording delay
        adjusted_entries = []
        for entry in entries:
            if entry.get('t') is not None:
                adjusted_entries.append({
                    **entry,
                    'adjusted_t': entry['t'] - self.transcript_delay_ms
                })
        
        # Sort by adjusted time
        adjusted_entries.sort(key=lambda e: e['adjusted_t'])
        
        # For each step, find the most recent voice command BEFORE it
        for step in steps:
            if 'timestamp' not in step or step['timestamp'] is None:
                continue
            
            step_timestamp = step['timestamp']
            relative_time = self._normalize_timestamp(step_timestamp, recording_start)
            
            if relative_time is None:
                continue
            
            # Find the most recent voice command before this action
            # (accounting for transcript delay)
            relevant_entry = None
            relevant_idx = None
            
            for idx, entry in enumerate(adjusted_entries):
                adjusted_time = entry['adjusted_t']
                
                # Voice command must be BEFORE the action
                if adjusted_time <= relative_time:
                    relevant_entry = entry
                    relevant_idx = idx
                else:
                    # Stop at first entry that's after the action
                    break
            
            if relevant_entry is None:
                continue
            
            # Calculate time offset (how long after voice the action occurred)
            time_offset = relative_time - relevant_entry['adjusted_t']
            
            # Check if this is within reasonable time (max 30 seconds)
            # If action is >30s after voice, likely unrelated
            if time_offset > 30000:
                continue
            
            # Calculate confidence based on:
            # 1. Proximity: closer actions are more confident
            # 2. Whether there's a NEXT voice command soon after
            next_entry = adjusted_entries[relevant_idx + 1] if relevant_idx + 1 < len(adjusted_entries) else None
            
            if next_entry:
                # If action is very close to NEXT voice command, reduce confidence
                time_to_next = next_entry['adjusted_t'] - relative_time
                if time_to_next < 1000:  # Action within 1s of next voice
                    # Might belong to next voice command instead
                    confidence = 0.4
                else:
                    # Calculate confidence: closer to current voice = higher confidence
                    segment_duration = next_entry['adjusted_t'] - relevant_entry['adjusted_t']
                    position_in_segment = time_offset / segment_duration if segment_duration > 0 else 0
                    # Earlier in segment = higher confidence
                    confidence = max(0.5, 1.0 - (position_in_segment * 0.5))
            else:
                # No next voice command, calculate confidence from time offset
                # Actions within 5s = high confidence, gradually decreases
                confidence = max(0.5, 1.0 - (time_offset / 30000))
            
            if confidence < self.min_confidence:
                continue
            
            # Create voice context
            voice_context = VoiceContext(
                relevant_text=relevant_entry['text'],
                transcript_index_start=relevant_idx,
                transcript_index_end=relevant_idx,
                time_offset_ms=-time_offset,  # Negative = voice was before action
                confidence=confidence,
                entries=[relevant_entry]
            )
            
            step['voiceContext'] = voice_context.to_dict()
            steps_with_context += 1
            
            logger.debug(
                f"Segment match: {step.get('type', 'unknown')} ← "
                f"'{relevant_entry['text'][:40]}...' "
                f"({time_offset}ms after voice, conf={confidence:.2f})"
            )
        
        return steps_with_context
    
    def _correlate_by_time_windows(
        self,
        steps: List[Dict[str, Any]],
        entries: List[Dict[str, Any]],
        recording_start: int
    ) -> int:
        """
        Legacy time-window based correlation.
        Kept for backward compatibility or special use cases.
        """
        steps_with_context = 0
        
        for step in steps:
            if 'timestamp' not in step or step['timestamp'] is None:
                continue
            
            step_timestamp = step['timestamp']
            relative_time = self._normalize_timestamp(step_timestamp, recording_start)
            
            if relative_time is None:
                logger.warning(f"Could not normalize timestamp for step: {step.get('type', 'unknown')}")
                continue
            
            # Find relevant transcript entries using time windows
            voice_context = self._find_voice_context(
                entries, relative_time, step
            )
            
            if voice_context:
                step['voiceContext'] = voice_context.to_dict()
                steps_with_context += 1
                logger.debug(
                    f"Added voice context to {step.get('type', 'unknown')} step: "
                    f"'{voice_context.relevant_text[:50]}...'"
                )
        
        return steps_with_context
    
    def _normalize_timestamp(
        self,
        step_timestamp: int,
        recording_start: int
    ) -> Optional[int]:
        """
        Convert step timestamp to relative time (ms from recording start).
        
        Handles both:
        - Absolute timestamps (Unix epoch ms)
        - Relative timestamps (already relative to start)
        
        Args:
            step_timestamp: Timestamp from workflow step
            recording_start: Recording start time (absolute Unix epoch ms)
        
        Returns:
            Relative time in ms, or None if cannot determine
        """
        # If step_timestamp is much larger than recording_start, it's absolute
        # Heuristic: if difference > 1 hour (3,600,000 ms), treat as absolute
        if step_timestamp > recording_start + 3_600_000:
            return step_timestamp - recording_start
        
        # If step_timestamp is close to recording_start, it might be relative already
        # Heuristic: if timestamp is less than 1 hour, assume it's relative
        if step_timestamp < 3_600_000:
            return step_timestamp
        
        # Otherwise, assume it's absolute and convert
        return step_timestamp - recording_start
    
    def _find_voice_context(
        self,
        entries: List[Dict[str, Any]],
        relative_time: int,
        step: Dict[str, Any]
    ) -> Optional[VoiceContext]:
        """
        Find transcript entries relevant to a workflow step.
        
        KEY INSIGHT: Transcript has 500-1000ms delay. If user speaks at t=5000,
        transcript might be recorded at t=5750. To match with action at t=5500,
        we adjust: adjusted_time = transcript_time - delay = 5750 - 750 = 5000,
        which is 500ms BEFORE the action (correct!).
        
        Args:
            entries: List of transcript entries with 't' (time) and 'text'
            relative_time: Step time relative to recording start (ms)
            step: The workflow step (for logging/context)
        
        Returns:
            VoiceContext or None if no relevant entries found
        """
        # Find entries within time window (accounting for transcript delay)
        # Since transcript is LATE by ~750ms, we need to look LATER in the transcript
        # for voice that happened before the action
        window_start = relative_time - self.time_window_before_ms + self.transcript_delay_ms
        window_end = relative_time + self.time_window_after_ms + self.transcript_delay_ms
        
        candidates: List[Tuple[int, Dict[str, Any], int]] = []  # (index, entry, adjusted_time)
        
        for idx, entry in enumerate(entries):
            entry_time = entry.get('t')
            if entry_time is None:
                continue
            
            # Adjust for transcript delay: user spoke EARLIER than recorded
            adjusted_time = entry_time - self.transcript_delay_ms
            
            if window_start <= entry_time <= window_end:
                candidates.append((idx, entry, adjusted_time))
        
        if not candidates:
            return None
        
        # If prefer_closest, only keep the single closest entry
        if self.prefer_closest and len(candidates) > 1:
            # Find the entry closest to the action time (after adjusting for delay)
            closest = min(candidates, key=lambda x: abs(x[2] - relative_time))
            candidates = [closest]
        
        # Split into before and after (using adjusted time)
        before = [(idx, e, adj_t) for idx, e, adj_t in candidates if adj_t <= relative_time]
        after = [(idx, e, adj_t) for idx, e, adj_t in candidates if adj_t > relative_time]
        
        # Prioritize "before" (user typically speaks before acting)
        # But include "after" if there's nothing before
        selected_entries = before if before else after
        
        if not selected_entries:
            return None
        
        # Calculate confidence based on temporal proximity (using adjusted time)
        time_diffs = [abs(adj_t - relative_time) for _, _, adj_t in selected_entries]
        min_time_diff = min(time_diffs)
        max_window = max(self.time_window_before_ms, self.time_window_after_ms)
        confidence = max(0.0, 1.0 - (min_time_diff / max_window))
        
        if confidence < self.min_confidence:
            return None
        
        # Extract indices and combine text
        indices = [idx for idx, _, _ in selected_entries]
        combined_text = ' '.join(
            e.get('text', '') for _, e, _ in selected_entries
            if e.get('text')
        ).strip()
        
        if not combined_text:
            return None
        
        # Calculate average time offset (using adjusted time, negative = before, positive = after)
        avg_time_offset = sum(adj_t - relative_time for _, _, adj_t in selected_entries) // len(selected_entries)
        
        return VoiceContext(
            relevant_text=combined_text,
            transcript_index_start=min(indices),
            transcript_index_end=max(indices),
            time_offset_ms=avg_time_offset,
            confidence=confidence,
            entries=[e for _, e, _ in selected_entries]
        )
    
    def analyze_intent_mismatch(
        self,
        workflow_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Analyze steps to find potential mismatches between voice intent and action.
        
        This can be used to:
        - Detect recording errors
        - Suggest optimizations
        - Improve step descriptions
        
        Args:
            workflow_data: Workflow with voiceContext already added
        
        Returns:
            List of potential mismatches with suggestions
        """
        mismatches = []
        
        for idx, step in enumerate(workflow_data.get('steps', [])):
            voice_context = step.get('voiceContext')
            if not voice_context:
                continue
            
            step_type = step.get('type', 'unknown')
            voice_text = voice_context.get('relevantText', '').lower()
            
            # Simple heuristic analysis
            # (In production, could use LLM for better analysis)
            
            # Example: User says "click" but action is "navigate"
            if 'click' in voice_text and step_type == 'navigate':
                mismatches.append({
                    'step_index': idx,
                    'type': 'action_mismatch',
                    'confidence': voice_context.get('confidence', 0),
                    'voice_intent': 'click action',
                    'actual_action': 'navigate',
                    'suggestion': 'User intended to click, consider using click action instead of navigate'
                })
            
            # Example: User says "type" or "enter" but action is "click"
            if ('type' in voice_text or 'enter' in voice_text) and step_type == 'click':
                mismatches.append({
                    'step_index': idx,
                    'type': 'action_mismatch',
                    'confidence': voice_context.get('confidence', 0),
                    'voice_intent': 'input text',
                    'actual_action': 'click',
                    'suggestion': 'User intended to type text, verify if input action is more appropriate'
                })
        
        return mismatches
    
    def enhance_step_descriptions(
        self,
        workflow_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enhance step descriptions using voice context.
        
        If a step has no description or a generic one, use the voice context
        to create a more meaningful description.
        
        Args:
            workflow_data: Workflow with voiceContext already added
        
        Returns:
            Workflow with enhanced descriptions
        """
        enhanced_count = 0
        
        for step in workflow_data.get('steps', []):
            voice_context = step.get('voiceContext')
            if not voice_context:
                continue
            
            current_desc = step.get('description', '').strip()
            voice_text = voice_context.get('relevantText', '').strip()
            
            # Enhance if no description or generic description
            if not current_desc or current_desc in ['No description', 'Step']:
                step['description'] = f"User said: '{voice_text}'"
                enhanced_count += 1
            elif len(current_desc) < 20:  # Very short description
                step['description'] = f"{current_desc} (User: '{voice_text}')"
                enhanced_count += 1
        
        if enhanced_count > 0:
            logger.info(f"Enhanced {enhanced_count} step descriptions with voice context")
        
        return workflow_data


def correlate_transcript_with_workflow(
    workflow_data: Dict[str, Any],
    transcript_data: Dict[str, Any],
    use_segments: bool = True,
    **correlator_kwargs
) -> Dict[str, Any]:
    """
    Convenience function to correlate transcript with workflow.
    
    Args:
        workflow_data: Workflow JSON
        transcript_data: Transcript JSON
        use_segments: If True, use segment-based correlation (recommended).
                     Each voice command applies to all subsequent actions
                     until the next voice command.
                     If False, use time-window based correlation (legacy).
        **correlator_kwargs: Additional arguments for TranscriptCorrelator
    
    Returns:
        Enhanced workflow with voiceContext
    """
    correlator = TranscriptCorrelator(**correlator_kwargs)
    enhanced_workflow = correlator.correlate_workflow(
        workflow_data, 
        transcript_data,
        use_segments=use_segments
    )
    
    # Optionally enhance descriptions
    enhanced_workflow = correlator.enhance_step_descriptions(enhanced_workflow)
    
    return enhanced_workflow

