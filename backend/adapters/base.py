from __future__ import annotations

import abc
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models import LiveEvent
    from backend.services.aggregator import Aggregator


class BaseAdapter(abc.ABC):
    """Base class for all platform adapters.

    Subclasses must implement `_connect()` and `_listen()`.
    The base class handles lifecycle, reconnection with exponential back‑off,
    and error isolation.
    """

    PLATFORM: str = ""

    def __init__(self, aggregator: Aggregator, room_id: str) -> None:
        self.aggregator = aggregator
        self.room_id = room_id
        self._running = False
        self._task: asyncio.Task | None = None
        self._log = logging.getLogger(f"{__name__}.{self.PLATFORM}")

    # -- public lifecycle ---------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self._log.info("started room=%s", self.room_id)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._log.info("stopped")

    # -- internal loop with auto-reconnect ----------------------------------

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                await self._connect()
                backoff = 1.0
                await self._listen()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log.exception("connection error, reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # -- hooks for subclasses -----------------------------------------------

    @abc.abstractmethod
    async def _connect(self) -> None:
        """Establish connection (WS / HTTP session)."""

    @abc.abstractmethod
    async def _listen(self) -> None:
        """Read messages in a loop; call `_emit()` for each event."""
