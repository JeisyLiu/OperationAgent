"""Server-Sent Events stream for UI push updates."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services.event_bus import event_bus

router = APIRouter(tags=["events"])


async def _event_stream():
    queue = await event_bus.subscribe()
    try:
        yield f"data: {json.dumps({'type': 'hello', 'payload': {}})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        raise
    finally:
        await event_bus.unsubscribe(queue)


@router.get("/api/events")
async def events_stream() -> StreamingResponse:
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
