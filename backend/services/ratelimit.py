from __future__ import annotations

import asyncio
import time
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple per-platform token-bucket rate limiter for outbound requests.

    Each platform has independent limits:
      - requests: max tokens (burst capacity)
      - refill_rate: tokens added per second (sustained rate)

    This prevents 429 errors by throttling HTTP requests to platform APIs.
    """

    def __init__(self, name: str, max_tokens: int = 10, refill_rate: float = 1.0) -> None:
        self.name = name
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # How long until next token?
                wait = (1.0 - self._tokens) / self.refill_rate
            logger.debug("%s rate limiter: waiting %.2fs", self.name, wait)
            await asyncio.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now


# Per-platform limiters
# Bilibili: their API is lenient; we batch via WS so rate limiting is less critical
# Douyin: aggressive anti-bot; keep requests very sparse
# Kuaishou: moderate anti-bot
bilibili_limiter = RateLimiter("bilibili", max_tokens=5, refill_rate=1.0)
douyin_limiter = RateLimiter("douyin", max_tokens=3, refill_rate=0.5)
kuaishou_limiter = RateLimiter("kuaishou", max_tokens=3, refill_rate=0.5)
