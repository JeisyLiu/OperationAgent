"""In-process event bus for SSE push (no polling)."""

from __future__ import annotations

import asyncio
from typing import Any

_main_loop: asyncio.AbstractEventLoop | None = None


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = {"type": event_type, "payload": payload or {}}
        async with self._lock:
            dead: list[asyncio.Queue] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.discard(queue)


event_bus = EventBus()


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def publish_sync(event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Thread-safe publish from sync API handlers."""
    if _main_loop is None or not _main_loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(event_bus.publish(event_type, payload), _main_loop)


async def publish(event_type: str, payload: dict[str, Any] | None = None) -> None:
    await event_bus.publish(event_type, payload)


def emit_job_updated(job_id: int, status: str) -> None:
    publish_sync("job.updated", {"job_id": job_id, "status": status})


def emit_worker_status(payload: dict[str, Any]) -> None:
    publish_sync("worker.status", payload)


def emit_readiness_changed() -> None:
    publish_sync("readiness.changed", {})
