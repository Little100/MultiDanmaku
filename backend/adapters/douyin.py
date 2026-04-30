from __future__ import annotations

import asyncio
import json
import logging
import re
import random
import string
from typing import Any
from urllib.parse import urlencode

import aiohttp

from backend.adapters.base import BaseAdapter
from backend.models import EventType, LiveEvent, Platform
from backend.services.aggregator import Aggregator
from backend.services.ratelimit import douyin_limiter

logger = logging.getLogger(__name__)


class DouyinAdapter(BaseAdapter):
    """Douyin (TikTok CN) live adapter.

    Connects to the Douyin live WebSocket to receive danmaku, gifts, and enter events.
    Douyin has strict anti-bot measures; the adapter uses:
      - Realistic browser headers / cookies (ttwid)
      - Rate limiting on HTTP requests (token bucket)
      - Exponential back-off on reconnect (handled by BaseAdapter)

    Note: Douyin's protocol changes frequently. If the binary protobuf parsing
    stops working, check for updated proto definitions or third-party libraries.
    """

    PLATFORM = "douyin"

    def __init__(self, aggregator: Aggregator, room_id: str) -> None:
        super().__init__(aggregator, room_id)
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._heartbeat_task: asyncio.Task | None = None

    async def _connect(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                "Referer": "https://live.douyin.com/",
            }
        )

        # Acquire ttwid cookie (rate-limited)
        await douyin_limiter.acquire()
        try:
            async with self._session.get("https://live.douyin.com/", allow_redirects=True) as resp:
                for cookie in self._session.cookie_jar:
                    if cookie.key == "ttwid":
                        logger.info("douyin: got ttwid cookie")
                        break
        except Exception:
            logger.warning("douyin: failed to get ttwid cookie, proceeding anyway")

        # Fetch room info (rate-limited)
        await douyin_limiter.acquire()
        room_info = None
        room_url = (
            "https://live.douyin.com/webcast/room/web/enter/"
            "?aid=6383&app_name=douyin_web&live_id=1"
            "&device_platform=web&language=zh-CN"
            "&browser_language=zh-CN&browser_platform=Win32"
            "&browser_name=Chrome&browser_version=127.0.0.0"
            f"&web_rid={self.room_id}"
        )
        try:
            async with self._session.get(room_url) as resp:
                data = await resp.json(content_type=None)
                rooms = data.get("data", {}).get("data", [])
                if rooms:
                    room_info = rooms[0]
        except Exception as e:
            logger.warning("douyin: failed to fetch room info: %s", e)

        if not room_info:
            raise ConnectionError(
                f"Cannot get Douyin room {self.room_id} info. "
                "The stream may be offline, cookies may be needed, or the room ID is invalid."
            )

        # Build WebSocket URL
        internal_room_id = room_info.get("id_str", self.room_id)
        ws_params = {
            "app_name": "douyin_web",
            "version_code": "580000",
            "webcast_sdk_version": "1.0.14",
            "update_version_code": "1.0.14",
            "compress": "gzip",
            "device_platform": "web",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "127.0.0.0",
            "internal_ext": json.dumps({
                "anchor_id": room_info.get("owner_user_id_str", ""),
                "room_id": internal_room_id,
            }),
        }
        ws_url = f"wss://webcast5-ws-web-lf.douyin.com/webcast/im/push/v2/?{urlencode(ws_params)}"

        try:
            self._ws = await self._session.ws_connect(ws_url)
        except Exception as e:
            raise ConnectionError(f"Douyin WebSocket connect failed: {e}")

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("douyin connected room=%s (internal=%s)", self.room_id, internal_room_id)

    async def _heartbeat_loop(self) -> None:
        """Douyin heartbeats are implicit (keep-alive via the WS transport)."""
        try:
            while self._ws and not self._ws.closed:
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def _listen(self) -> None:
        async for msg in self._ws:
            if msg.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                try:
                    if isinstance(msg.data, bytes):
                        self._handle_binary(msg.data)
                    else:
                        self._handle_text(msg.data)
                except Exception:
                    logger.debug("douyin: failed to parse message", exc_info=True)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
        raise ConnectionError("douyin ws closed")

    def _handle_binary(self, data: bytes) -> None:
        """Heuristic extraction of danmaku from protobuf-encoded binary messages.

        This is a fallback. For reliable parsing, integrate a douyin proto library.
        """
        text_parts = self._extract_strings(data)
        if len(text_parts) >= 2:
            for i, part in enumerate(text_parts):
                content = text_parts[i + 1] if i + 1 < len(text_parts) else ""
                if content and len(content) <= 100 and len(part) <= 30:
                    self.aggregator.publish(
                        LiveEvent(
                            platform=Platform.DOUYIN,
                            room_id=self.room_id,
                            event_type=EventType.DANMAKU,
                            username=part,
                            content=content,
                            raw={"type": "binary_heuristic"},
                        )
                    )
                    break

    def _handle_text(self, data: str) -> None:
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return

        method = obj.get("method", "")
        payload = obj.get("payload", {})

        if method == "WebcastChatMessage":
            user = payload.get("user", {})
            self.aggregator.publish(
                LiveEvent(
                    platform=Platform.DOUYIN,
                    room_id=self.room_id,
                    event_type=EventType.DANMAKU,
                    username=user.get("nickname", "unknown"),
                    content=payload.get("content", ""),
                    avatar=user.get("avatar_thumb", {}).get("url_list", [None])[0],
                    raw=obj,
                )
            )
        elif method == "WebcastGiftMessage":
            user = payload.get("user", {})
            gift = payload.get("gift", {})
            self.aggregator.publish(
                LiveEvent(
                    platform=Platform.DOUYIN,
                    room_id=self.room_id,
                    event_type=EventType.GIFT,
                    username=user.get("nickname", "unknown"),
                    content=f"{gift.get('name', '?')} x{payload.get('repeat_count', 1)}",
                    avatar=user.get("avatar_thumb", {}).get("url_list", [None])[0],
                    raw=obj,
                )
            )
        elif method == "WebcastMemberMessage":
            user = payload.get("user", {})
            self.aggregator.publish(
                LiveEvent(
                    platform=Platform.DOUYIN,
                    room_id=self.room_id,
                    event_type=EventType.ENTER,
                    username=user.get("nickname", "unknown"),
                    content="entered the live room",
                    avatar=user.get("avatar_thumb", {}).get("url_list", [None])[0],
                    raw=obj,
                )
            )
        elif method == "WebcastLikeMessage":
            user = payload.get("user", {})
            self.aggregator.publish(
                LiveEvent(
                    platform=Platform.DOUYIN,
                    room_id=self.room_id,
                    event_type=EventType.LIKE,
                    username=user.get("nickname", "unknown"),
                    content=f"liked ({payload.get('count', 1)})",
                    avatar=user.get("avatar_thumb", {}).get("url_list", [None])[0],
                    raw=obj,
                )
            )

    @staticmethod
    def _extract_strings(data: bytes, min_len: int = 2) -> list[str]:
        """Extract all plausible UTF-8 string fragments from binary data."""
        results: list[str] = []
        current = bytearray()
        for byte in data:
            if 32 <= byte <= 126 or byte >= 0xC0:
                current.append(byte)
            else:
                if len(current) >= min_len:
                    try:
                        s = current.decode("utf-8", errors="ignore")
                        if s and len(s) >= min_len:
                            results.append(s)
                    except Exception:
                        pass
                current = bytearray()
        if len(current) >= min_len:
            try:
                s = current.decode("utf-8", errors="ignore")
                if s and len(s) >= min_len:
                    results.append(s)
            except Exception:
                pass
        return results

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        await super().stop()
