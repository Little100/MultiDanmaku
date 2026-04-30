from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import struct
import time
import uuid
import zlib
from typing import Any

import aiohttp

from backend.adapters.base import BaseAdapter
from backend.models import EventType, LiveEvent, Platform
from backend.services.aggregator import Aggregator
from backend.services.ratelimit import bilibili_limiter

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - optional dependency
    async_playwright = None

logger = logging.getLogger(__name__)

HEADER_FMT = ">IHHII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
WS_URL = "wss://broadcastlv.chat.bilibili.com/sub"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://live.bilibili.com/",
}


# -- Open Platform adapter (身份码 + 凭证 → 直连 B 站 Open Platform WS) ----

class BilibiliOpenPlatformAdapter(BaseAdapter):
    """Bilibili adapter via Open Live Platform.

    Uses the official Bilibili Open Live API:
    1. POST /v2/app/start with identity code → get wss_link + auth_body
    2. Connect to the Open Platform WebSocket
    3. Parse Open Platform message formats (LIVE_OPEN_PLATFORM_DM, etc.)

    This is the same approach used by chat.vrp.moe.
    """

    PLATFORM = "bilibili"

    def __init__(
        self,
        aggregator: Aggregator,
        room_id: str,
        app_id: str = "",
        access_key: str = "",
        access_secret: str = "",
    ) -> None:
        super().__init__(aggregator, room_id)
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._app_id = app_id.strip()
        self._access_key = access_key.strip()
        self._access_secret = access_secret.strip()
        self._game_id: str = ""

    async def _connect(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            start_data = await self._start_game()
            wss_link = start_data["wss_link"]
            auth_body = start_data["auth_body"]
            self._game_id = start_data.get("game_id", "")
            logger.info("bilibili open: connecting to %s", wss_link)
            self._ws = await self._session.ws_connect(wss_link)
            await self._ws.send_str(auth_body)
            logger.info("bilibili open: auth sent, game_id=%s", self._game_id)
        except Exception:
            await self._cleanup()
            raise

    async def _listen(self) -> None:
        if not self._ws:
            raise ConnectionError("Open Platform adapter not initialized")
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._handle_message(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                self._handle_binary(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
        raise ConnectionError("Bilibili Open Platform WebSocket closed")

    # -- Open Live API --------------------------------------------------------

    async def _start_game(self) -> dict[str, str]:
        """Call /v2/app/start to get WebSocket info."""
        url = "https://live-open.biliapi.com/v2/app/start"
        code = self.room_id.strip().upper()
        body = json.dumps({"code": code, "app_id": int(self._app_id)}, separators=(",", ":"))
        body_bytes = body.encode("utf-8")
        body_md5 = hashlib.md5(body_bytes).hexdigest()
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex

        header_str = (
            f"x-bili-accesskeyid:{self._access_key}\n"
            f"x-bili-content-md5:{body_md5}\n"
            f"x-bili-signature-method:HMAC-SHA256\n"
            f"x-bili-signature-nonce:{nonce}\n"
            f"x-bili-signature-version:1.0\n"
            f"x-bili-timestamp:{timestamp}"
        )
        signature = hmac.new(
            self._access_secret.encode("utf-8"),
            header_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "x-bili-accesskeyid": self._access_key,
            "x-bili-content-md5": body_md5,
            "x-bili-signature-method": "HMAC-SHA256",
            "x-bili-signature-nonce": nonce,
            "x-bili-signature-version": "1.0",
            "x-bili-timestamp": timestamp,
            "Authorization": signature,
            "Content-Type": "application/json",
        }

        async with self._session.post(url, data=body_bytes, headers=headers) as resp:
            data = await resp.json()
            if data.get("code") != 0:
                raise ConnectionError(
                    f"Open Live API error: code={data.get('code')}, message={data.get('message', '')}. "
                    "请检查身份码和凭证是否正确。"
                )
            result = data.get("data", {})
            ws_info = result.get("websocket_info", {})
            anchor = result.get("anchor_info", {})
            wss_links = ws_info.get("wss_link", [])
            auth_body = ws_info.get("auth_body", "")
            if not wss_links or not auth_body:
                raise ConnectionError("Open Live API: missing wss_link or auth_body")
            logger.info("bilibili open: room_id=%d, uid=%d", anchor.get("room_id", 0), anchor.get("uid", 0))
            return {
                "wss_link": wss_links[0],
                "auth_body": auth_body,
                "game_id": result.get("game_info", {}).get("game_id", ""),
            }

    # -- message parsing (Open Platform format) --------------------------------

    def _handle_message(self, raw: str) -> None:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return

        cmd = obj.get("cmd", "")
        data = obj.get("data")

        if not data or not isinstance(data, dict):
            return

        if cmd == "LIVE_OPEN_PLATFORM_DM":
            self._on_dm(data)
        elif cmd == "LIVE_OPEN_PLATFORM_SEND_GIFT":
            self._on_gift(data)
        elif cmd == "LIVE_OPEN_PLATFORM_SUPER_CHAT":
            self._on_superchat(data)
        elif cmd == "LIVE_OPEN_PLATFORM_LIKE":
            self._on_like(data)
        elif cmd == "LIVE_OPEN_PLATFORM_LIVE_ROOM_ENTER":
            self._on_enter(data)
        elif cmd == "LIVE_OPEN_PLATFORM_GUARD":
            self._on_guard(data)

    def _handle_binary(self, data: bytes) -> None:
        """Handle binary frames (protover 2 = zlib compressed)."""
        if len(data) < HEADER_SIZE:
            return
        total, hlen, proto, op, _seq = struct.unpack_from(HEADER_FMT, data, 0)
        body = data[hlen:total]
        if proto == 2:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                return
        try:
            self._handle_message(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

    # -- event handlers -------------------------------------------------------

    def _on_dm(self, data: dict[str, Any]) -> None:
        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=EventType.DANMAKU,
            username=data.get("uname", ""),
            content=data.get("msg", ""),
            avatar=data.get("uface") or None,
            raw=data,
        ))

    def _on_gift(self, data: dict[str, Any]) -> None:
        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=EventType.GIFT,
            username=data.get("uname", ""),
            content=f"{data.get('gift_name', '')} x{data.get('gift_num', 1)}",
            avatar=data.get("uface") or None,
            raw=data,
        ))

    def _on_superchat(self, data: dict[str, Any]) -> None:
        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=EventType.GIFT,
            username=data.get("uname", ""),
            content=f"SC ¥{data.get('rmb', 0)} {data.get('message', '')}",
            avatar=data.get("uface") or None,
            raw=data,
        ))

    def _on_like(self, data: dict[str, Any]) -> None:
        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=EventType.LIKE,
            username=data.get("uname", ""),
            content="点赞",
            avatar=data.get("uface") or None,
            raw=data,
        ))

    def _on_enter(self, data: dict[str, Any]) -> None:
        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=EventType.ENTER,
            username=data.get("uname", ""),
            content="进入直播间",
            avatar=data.get("uface") or None,
            raw=data,
        ))

    def _on_guard(self, data: dict[str, Any]) -> None:
        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=EventType.GIFT,
            username=data.get("uname", ""),
            content=f"开通 {data.get('guard_name', data.get('gift_name', ''))}",
            avatar=data.get("uface") or None,
            raw=data,
        ))

    # -- cleanup --------------------------------------------------------------

    async def _cleanup(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def stop(self) -> None:
        await self._cleanup()
        await super().stop()


# -- Direct Bilibili internal WebSocket adapter (数字房间号) -----------------

class BilibiliDirectAdapter(BaseAdapter):
    """Bilibili adapter using the internal WebSocket protocol.

    Connects directly to wss://broadcastlv.chat.bilibili.com/sub.
    Only works with numeric room IDs.
    """

    PLATFORM = "bilibili"

    def __init__(self, aggregator: Aggregator, room_id: str) -> None:
        super().__init__(aggregator, room_id)
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._real_room_id: int = 0
        self._token: str = ""

    async def _connect(self) -> None:
        self._session = aiohttp.ClientSession(headers=DEFAULT_HEADERS)
        try:
            await bilibili_limiter.acquire()
            self._real_room_id = await self._resolve_room()
            self._token = await self._fetch_token(self._real_room_id)
            self._ws = await self._session.ws_connect(WS_URL)
            await self._send_auth()
            logger.info("bilibili direct: connected room=%d", self._real_room_id)
        except Exception:
            await self._cleanup()
            raise

    async def _listen(self) -> None:
        if not self._ws:
            raise ConnectionError("Not initialized")
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                self._handle_packet(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
        raise ConnectionError("WebSocket closed")

    async def _resolve_room(self) -> int:
        try:
            room_id = int(self.room_id)
        except ValueError:
            raise ConnectionError(
                f"Bilibili: '{self.room_id}' 不是数字房间号。"
                "请填入数字房间号，或使用身份码+开放平台凭证。"
            )
        url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
        async with self._session.get(url) as resp:
            data = await resp.json()
            if data.get("code") != 0:
                raise ConnectionError(f"Room info error: {data}")
            return data["data"]["room_id"]

    async def _fetch_token(self, room_id: int) -> str:
        url = f"https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo?id={room_id}"
        async with self._session.get(url) as resp:
            data = await resp.json()
            if data.get("code") != 0:
                return ""
            return data.get("data", {}).get("token", "")

    async def _send_auth(self) -> None:
        payload = {"uid": 0, "roomid": self._real_room_id, "protover": 2, "platform": "web", "type": 2, "clientver": "2.7.7"}
        if self._token:
            payload["key"] = self._token
        await self._send_packet(7, json.dumps(payload).encode())

    async def _send_packet(self, op: int, body: bytes) -> None:
        header = struct.pack(HEADER_FMT, HEADER_SIZE + len(body), HEADER_SIZE, 1, op, 1)
        if self._ws:
            await self._ws.send_bytes(header + body)

    def _handle_packet(self, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            if offset + HEADER_SIZE > len(data):
                break
            total, hlen, proto, op, _seq = struct.unpack_from(HEADER_FMT, data, offset)
            if total < hlen or offset + total > len(data):
                break
            body = data[offset + hlen : offset + total]
            if proto == 2:
                try:
                    self._handle_packet(zlib.decompress(body))
                except zlib.error:
                    pass
            elif op == 5:
                self._handle_message(body)
            elif op == 8:
                logger.info("bilibili direct: auth success")
            offset += total

    def _handle_message(self, raw: bytes) -> None:
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        cmd = obj.get("cmd", "")
        info = obj.get("info")
        data = obj.get("data")

        if cmd == "DANMU_MSG" and info:
            try:
                user = info[2]
                self.aggregator.publish(LiveEvent(
                    platform=Platform.BILIBILI, room_id=self.room_id, event_type=EventType.DANMAKU,
                    username=str(user[1]) if len(user) > 1 else "unknown",
                    content=str(info[1]) if len(info) > 1 else "", raw={"cmd": "DANMU_MSG"},
                ))
            except (IndexError, TypeError):
                pass
        elif cmd == "SEND_GIFT" and data:
            self.aggregator.publish(LiveEvent(
                platform=Platform.BILIBILI, room_id=self.room_id, event_type=EventType.GIFT,
                username=data.get("uname", ""),
                content=f"{data.get('action', '')} x{data.get('num', 1)} {data.get('giftName', '')}",
                raw={"cmd": "SEND_GIFT"},
            ))
        elif cmd == "SUPER_CHAT_MESSAGE" and data:
            ui = data.get("user_info", {})
            self.aggregator.publish(LiveEvent(
                platform=Platform.BILIBILI, room_id=self.room_id, event_type=EventType.GIFT,
                username=ui.get("uname", ""),
                content=f"SC ¥{data.get('price', 0)} {data.get('message', '')}",
                raw={"cmd": "SUPER_CHAT_MESSAGE"},
            ))
        elif cmd == "GUARD_BUY" and data:
            self.aggregator.publish(LiveEvent(
                platform=Platform.BILIBILI, room_id=self.room_id, event_type=EventType.GIFT,
                username=data.get("username", ""),
                content=f"开通 {data.get('gift_name', '')}",
                raw={"cmd": "GUARD_BUY"},
            ))
        elif cmd == "INTERACT_WORD" and data:
            if data.get("msg_type") == 1:
                self.aggregator.publish(LiveEvent(
                    platform=Platform.BILIBILI, room_id=self.room_id, event_type=EventType.ENTER,
                    username=data.get("uname", ""), content="进入直播间",
                    raw={"cmd": "INTERACT_WORD"},
                ))

    async def _cleanup(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._token = ""

    async def stop(self) -> None:
        await self._cleanup()
        await super().stop()


# -- chat.vrp.moe OBS URL adapter ------------------------------------------

_JS_OBSERVER = """
(() => {
  if (window.__md_hooked) return;
  window.__md_hooked = true;

  const publish = (data) => {
    try {
      window.__md_event(JSON.stringify(data));
    } catch(e) {
      console.log('[md] publish error:', e.message);
    }
  };

  const parseEvent = (el) => {
    if (!(el instanceof HTMLElement) || !el.classList.contains('event')) return null;

    const classes = Array.from(el.classList);
    let eventType = 'unknown';
    for (const c of classes) {
      if (c.startsWith('event-type--')) { eventType = c.replace('event-type--', ''); break; }
    }

    const uid = el.dataset.uid || '';
    const ts = parseInt(el.dataset.timestamp || '0', 10);
    const usernameEl = el.querySelector('.username-text');
    const messageEl = el.querySelector('.message');
    const avatarEl = el.querySelector('.sender-avatar img.avatar') || el.querySelector('img.avatar');

    const username = usernameEl ? usernameEl.textContent.trim() : '';
    const message = messageEl ? messageEl.textContent.trim() : (el.textContent || '').trim();
    const avatar = avatarEl ? (avatarEl.getAttribute('src') || '') : '';

    return { eventType, uid, timestamp: ts, username, message, avatar };
  };

  const scan = (root) => {
    if (!(root instanceof HTMLElement)) return;
    if (root.classList && root.classList.contains('event')) {
      const parsed = parseEvent(root);
      if (parsed) {
        console.log('[md] event:', parsed.eventType, parsed.username, parsed.message);
        publish(parsed);
      }
    }
    root.querySelectorAll && root.querySelectorAll('.event').forEach(el => {
      const parsed = parseEvent(el);
      if (parsed) {
        console.log('[md] event:', parsed.eventType, parsed.username, parsed.message);
        publish(parsed);
      }
    });
  };

  console.log('[md] observer installing...');
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const n of m.addedNodes) scan(n);
    }
  });

  const start = () => {
    observer.observe(document.body, { childList: true, subtree: true });
    console.log('[md] observer active, body children:', document.body.children.length);
  };

  if (document.body) {
    start();
  } else {
    document.addEventListener('DOMContentLoaded', start);
  }
})();
"""


class BilibiliChatUrlAdapter(BaseAdapter):
    """Bilibili adapter that reads events from a chat.vrp.moe OBS URL.

    Opens the URL in a headless Playwright browser, injects a MutationObserver
    that parses .event DOM elements, and converts them into MultiDanmaku LiveEvents.

    This leverages chat.vrp.moe's Bilibili connection — user just pastes the OBS URL.
    """

    PLATFORM = "bilibili"

    def __init__(self, aggregator: Aggregator, room_id: str, chat_url: str = "") -> None:
        super().__init__(aggregator, room_id)
        self._chat_url = chat_url.strip()
        self._browser = None
        self._page = None
        self._pw = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)

    async def _connect(self) -> None:
        if not self._chat_url:
            raise ConnectionError("chat.vrp.moe OBS URL is empty")
        if async_playwright is None:
            raise ConnectionError(
                "Playwright is not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-infobars",
            ],
        )
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        self._page = await context.new_page()

        # Forward browser console to Python logger for debugging
        self._page.on("console", lambda msg: logger.info("[browser] %s", msg.text))

        await self._page.expose_function("__md_event", self._on_dom_event)
        await self._page.add_init_script(_JS_OBSERVER)

        logger.info("bilibili chat-url: opening %s", self._chat_url[:80])
        await self._page.goto(self._chat_url, wait_until="networkidle")
        # Re-inject in case init script ran before expose_function was ready
        await self._page.evaluate(_JS_OBSERVER)
        logger.info("bilibili chat-url: page loaded, observer active")

    async def _listen(self) -> None:
        if not self._page:
            raise ConnectionError("Page not initialized")
        while self._running:
            if self._page.is_closed():
                break
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._publish_event(item)
        raise ConnectionError("chat.vrp.moe page closed")

    def _on_dom_event(self, raw_json: str) -> None:
        try:
            obj = json.loads(raw_json)
            self._queue.put_nowait(obj)
        except (json.JSONDecodeError, asyncio.QueueFull):
            pass

    # Event type mapping from chat.vrp.moe DOM classes
    _TYPE_MAP = {
        "message": EventType.DANMAKU,
        "gift": EventType.GIFT,
        "superchat": EventType.GIFT,
        "toast": EventType.GIFT,
        "interaction": EventType.ENTER,
        "like": EventType.LIKE,
        "system": EventType.SYSTEM,
    }

    def _publish_event(self, obj: dict[str, Any]) -> None:
        et = obj.get("eventType", "")
        event_type = self._TYPE_MAP.get(et)
        if event_type is None:
            return
        # Skip system messages (room connected, etc.)
        if et == "system":
            return

        username = obj.get("username", "")
        message = obj.get("message", "")
        avatar = obj.get("avatar") or None

        # For interactions, try to distinguish enter vs follow
        if et == "interaction":
            if "进入" in message or "入场" in message:
                event_type = EventType.ENTER
            elif "关注" in message:
                event_type = EventType.FOLLOW
            else:
                event_type = EventType.ENTER

        self.aggregator.publish(LiveEvent(
            platform=Platform.BILIBILI,
            room_id=self.room_id,
            event_type=event_type,
            username=username,
            content=message,
            avatar=avatar,
            raw=obj,
        ))

    async def _cleanup(self) -> None:
        if self._page and not self._page.is_closed():
            try:
                await self._page.close()
            except Exception:
                pass
        self._page = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = None

    async def stop(self) -> None:
        await self._cleanup()
        await super().stop()
