"""
Logging extensions for real-time log broadcasting.

- execution_id_var: ContextVar carrying current execution id
- ExecutionIdFilter: injects execution_id into LogRecord if missing
- LogBroadcastHandler: forwards log records to a publish/subscribe hub
- LogBroadcastHub: minimal in-memory pub/sub for later WebSocket/SSE wiring

This file has no dependency on FastAPI/WS. The WS route can subscribe
callbacks later to receive per-execution log payloads.
"""

from __future__ import annotations

import asyncio
import time
import logging
from contextvars import ContextVar
from typing import Awaitable, Callable, Dict, Optional, Set, List
from collections import deque


# Context variable to tag logs with execution scope
execution_id_var: ContextVar[Optional[str]] = ContextVar("execution_id", default=None)


class ExecutionIdFilter(logging.Filter):
    """Logging filter that ensures record.execution_id is set.

    Priority order:
    - keep existing record.execution_id if provided via LoggerAdapter/extra
    - otherwise, pull from execution_id_var ContextVar (may be None)
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            if not hasattr(record, "execution_id"):
                setattr(record, "execution_id", execution_id_var.get())
            return True
        except Exception:
            # Never block logging due to filter errors
            return True


class LogBroadcastHub:
    """A lightweight async pub/sub hub keyed by execution_id.

    Subscribers register an async callback taking a payload dict.
    """

    _global_instance: Optional["LogBroadcastHub"] = None

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[Callable[[dict], Awaitable[None]]]] = {}
        # Per-execution history buffer
        self._history: Dict[str, deque] = {}
        self._history_updated_at: Dict[str, float] = {}
        self.MAX_HISTORY: int = 200
        self.HISTORY_TTL_SEC: int = 180  # 3 minutes

    @classmethod
    def get_global(cls) -> "LogBroadcastHub":
        if cls._global_instance is None:
            cls._global_instance = LogBroadcastHub()
        return cls._global_instance

    def subscribe(self, execution_id: str, callback: Callable[[dict], Awaitable[None]]) -> None:
        if execution_id not in self._subscribers:
            self._subscribers[execution_id] = set()
        self._subscribers[execution_id].add(callback)

    def unsubscribe(self, execution_id: str, callback: Callable[[dict], Awaitable[None]]) -> None:
        try:
            callbacks = self._subscribers.get(execution_id)
            if callbacks and callback in callbacks:
                callbacks.remove(callback)
                if not callbacks:
                    self._subscribers.pop(execution_id, None)
        except Exception:
            pass

    def publish(self, execution_id: Optional[str], payload: dict) -> int:
        """Publish payload to all subscribers of execution_id.

        Returns number of callbacks scheduled. If execution_id is None,
        nothing is published (no-op).
        """
        if not execution_id:
            return 0
        # Append to history with TTL management
        try:
            self._append_history(execution_id, payload)
            self._purge_expired()
        except Exception:
            pass
        callbacks = self._subscribers.get(execution_id)
        if not callbacks:
            return 0

        scheduled = 0
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None  # allow silent no-op if no loop

        for cb in list(callbacks):
            try:
                coro = cb(payload)
                if asyncio.iscoroutine(coro):
                    if loop:
                        asyncio.create_task(coro)  # fire-and-forget
                        scheduled += 1
                # If callback returned non-coroutine, ignore
            except Exception:
                # Never raise from publishers
                continue
        return scheduled

    # ── History helpers ─────────────────────────────────────────────────────
    def _append_history(self, execution_id: str, payload: dict) -> None:
        if execution_id not in self._history:
            self._history[execution_id] = deque(maxlen=self.MAX_HISTORY)
        # Store a shallow copy so later mutation won't affect stored event
        try:
            entry = dict(payload)
        except Exception:
            entry = payload
        self._history[execution_id].append(entry)
        self._history_updated_at[execution_id] = time.time()

    def get_history(self, execution_id: str) -> List[dict]:
        buf = self._history.get(execution_id)
        if not buf:
            return []
        # Return a list copy
        return list(buf)

    def _purge_expired(self) -> None:
        if not self._history_updated_at:
            return
        now = time.time()
        expired: List[str] = []
        for exec_id, ts in list(self._history_updated_at.items()):
            if now - ts > self.HISTORY_TTL_SEC:
                expired.append(exec_id)
        for exec_id in expired:
            try:
                self._history.pop(exec_id, None)
                self._history_updated_at.pop(exec_id, None)
            except Exception:
                pass


class LogBroadcastHandler(logging.Handler):
    """Logging handler that forwards log records to LogBroadcastHub.

    Use alongside a file/console handler. This does not perform formatting
    for human readability; it constructs a structured payload for clients.
    """

    def __init__(self, hub: Optional[LogBroadcastHub] = None, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self.hub = hub or LogBroadcastHub.get_global()

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        try:
            # Ensure execution_id attribute exists (filter should have done it)
            execution_id = getattr(record, "execution_id", None)
            if execution_id is None:
                # Fallback to ContextVar in case logger filters didn't run at this level
                try:
                    execution_id = execution_id_var.get()
                except Exception:
                    execution_id = None
            message = record.getMessage()
            payload = {
                "type": "log",
                "timestamp": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                "execution_id": execution_id,
                "pathname": record.pathname,
                "lineno": record.lineno,
            }
            self.hub.publish(execution_id, payload)
        except Exception:
            # Logging must never fail the app
            pass


