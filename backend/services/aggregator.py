from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from fastapi import WebSocket

from backend.models import LiveEvent

logger = logging.getLogger(__name__)


class Aggregator:
    """Central hub that receives events from all adapters and broadcasts to WebSocket clients."""

    def __init__(self, max_queue_size: int = 500, history_size: int = 1000) -> None:
        self._clients: set[WebSocket] = set()
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._broadcast_task: asyncio.Task | None = None
        self._history: deque[LiveEvent] = deque(maxlen=history_size)

    # -- client management --------------------------------------------------

    async def add_client(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        logger.info("client connected (%d total)", len(self._clients))

    def remove_client(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.info("client disconnected (%d total)", len(self._clients))

    # -- history ------------------------------------------------------------

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        events = list(self._history)[-limit:]
        return [e.to_dict() for e in events]

    def clear_history(self) -> None:
        self._history.clear()

    # -- event intake -------------------------------------------------------

    def publish(self, event: LiveEvent) -> None:
        self._history.append(event)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # drop oldest to make room
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # -- broadcast loop -----------------------------------------------------

    async def start(self) -> None:
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info("aggregator started")

    async def stop(self) -> None:
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass

    async def _broadcast_loop(self) -> None:
        while True:
            event = await self._queue.get()
            payload = event.to_dict()
            dead: list[WebSocket] = []
            for ws in list(self._clients):
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.remove_client(ws)
