"""
Analyzer module for workflow analysis and optimization.

This module provides services for analyzing workflows, including:
- Transcript correlation with workflow steps
- Voice intent analysis
- Step optimization based on user intent
"""

from workflow_use.analyzer.transcript_correlator import TranscriptCorrelator

__all__ = ['TranscriptCorrelator']

