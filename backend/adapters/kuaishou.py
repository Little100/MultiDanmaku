from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import aiohttp

from backend.adapters.base import BaseAdapter
from backend.models import EventType, LiveEvent, Platform
from backend.services.aggregator import Aggregator
from backend.services.ratelimit import kuaishou_limiter

logger = logging.getLogger(__name__)


class KuaishouAdapter(BaseAdapter):
    """Kuaishou adapter based on the Live_Barrage polling approach.

    Instead of connecting to the private desktop WebSocket protocol, this adapter:
    1. Fetches the live room page
    2. Extracts liveStreamId from the embedded HTML / initial state
    3. Polls the mobile feed endpoint:
         https://livev.m.chenzhongtech.com/wap/live/feed?liveStreamId=...
    4. Converts the returned feed items into unified events

    This is simpler and much more stable than reverse-engineering the dynamic WS.
    Tradeoff: it behaves like polling, not a true push connection.
    """

    PLATFORM = "kuaishou"

    def __init__(self, aggregator: Aggregator, room_id: str) -> None:
        super().__init__(aggregator, room_id)
        self._session: aiohttp.ClientSession | None = None
        self._live_stream_id: str = ""
        self._seen_ids: set[str] = set()

    async def _connect(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                "Referer": "https://live.kuaishou.com/",
                "Origin": "https://live.kuaishou.com",
            }
        )

        try:
            await kuaishou_limiter.acquire()
            page_url = f"https://live.kuaishou.com/u/{self.room_id}"
            async with self._session.get(page_url) as resp:
                html = await resp.text()
                logger.info("kuaishou: fetched page status=%s length=%d", resp.status, len(html))

            patterns = [
                r'"liveStream"\s*:\s*\{\s*"id"\s*:\s*"([^"]+)"',
                r'"liveStreamId"\s*:\s*"([^"]+)"',
                r'liveStreamId=([0-9A-Za-z_\-]+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, html)
                if match:
                    self._live_stream_id = match.group(1)
                    break

            if not self._live_stream_id:
                raise ConnectionError(
                    "Kuaishou: could not extract liveStreamId from page. "
                    "The room may not be live or the page structure changed."
                )

            logger.info("kuaishou: extracted liveStreamId=%s", self._live_stream_id)
        except Exception:
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None
            raise

    async def _listen(self) -> None:
        if not self._session or not self._live_stream_id:
            raise ConnectionError("Kuaishou adapter not initialized")

        while self._running:
            await kuaishou_limiter.acquire()
            feed_url = f"https://livev.m.chenzhongtech.com/wap/live/feed?liveStreamId={self._live_stream_id}"
            async with self._session.get(feed_url) as resp:
                text = await resp.text()

            payload = self._decode_feed_payload(text)
            if payload is False:
                raise ConnectionError("Kuaishou: feed endpoint returned invalid payload")

            feeds = payload.get("liveStreamFeeds") or []
            for item in feeds:
                self._publish_feed_item(item)

            await asyncio.sleep(2.0)

    def _decode_feed_payload(self, text: str) -> dict[str, Any] | bool:
        """Live_Barrage's implementation json.loads twice; keep that compatibility."""
        try:
            data = json.loads(text)
            if isinstance(data, str):
                data = json.loads(data)
            return data
        except Exception:
            return False

    def _publish_feed_item(self, item: dict[str, Any]) -> None:
        author = item.get("author") or {}
        feed_id = str(item.get("id") or item.get("time") or "")
        if feed_id and feed_id in self._seen_ids:
            return
        if feed_id:
            self._seen_ids.add(feed_id)
            if len(self._seen_ids) > 5000:
                self._seen_ids = set(list(self._seen_ids)[-2000:])

        content = item.get("content") or ""
        username = author.get("userName") or author.get("nickname") or "unknown"
        avatar = self._extract_avatar(author)

        event_type = EventType.DANMAKU
        if not content:
            content = "message"

        self.aggregator.publish(
            LiveEvent(
                platform=Platform.KUAISHOU,
                room_id=self.room_id,
                event_type=event_type,
                username=username,
                content=content,
                avatar=avatar,
                raw=item,
            )
        )

    def _extract_avatar(self, author: dict[str, Any]) -> str | None:
        """Try multiple known Kuaishou author avatar field shapes."""
        candidates: list[Any] = [
            author.get("headUrl"),
            author.get("avatar"),
            author.get("avatarUrl"),
            author.get("img"),
            author.get("userHeadUrl"),
            author.get("headurl"),
            author.get("avatarurl"),
        ]

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, dict):
                for key in ("url", "src", "default", "headUrl", "avatar"):
                    value = candidate.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                url_list = candidate.get("urlList") or candidate.get("url_list")
                if isinstance(url_list, list):
                    for value in url_list:
                        if isinstance(value, str) and value.strip():
                            return value.strip()
            if isinstance(candidate, list):
                for value in candidate:
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                    if isinstance(value, dict):
                        inner = value.get("url") or value.get("src")
                        if isinstance(inner, str) and inner.strip():
                            return inner.strip()

        return None

    async def stop(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._live_stream_id = ""
        await super().stop()
