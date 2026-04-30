from __future__ import annotations

import asyncio
import logging
import pathlib
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Request, UploadFile, File as FastAPIFile
from fastapi.responses import HTMLResponse, FileResponse, Response
import aiohttp

from backend.adapters.bilibili import BilibiliChatUrlAdapter, BilibiliDirectAdapter, BilibiliOpenPlatformAdapter
from backend.adapters.douyin import DouyinAdapter
from backend.adapters.kuaishou import KuaishouAdapter
from backend.adapters.base import BaseAdapter
from backend.config import AppConfig, load_config, save_config
from backend.services.aggregator import Aggregator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

aggregator = Aggregator()
config = load_config()
active_adapters: dict[str, BaseAdapter] = {}

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend"


def _verify_token(x_token: str | None = None) -> None:
    """Raise 403 if a token is configured and the request doesn't carry it."""
    if config.token and x_token != config.token:
        raise HTTPException(status_code=403, detail="Invalid or missing token.")


def _make_adapter(name: str, pcfg):
    if name == "bilibili":
        if pcfg.chat_url:
            return BilibiliChatUrlAdapter(aggregator, pcfg.room_id.strip(), chat_url=pcfg.chat_url)
        if pcfg.open_live_app_id and pcfg.open_live_access_key and pcfg.open_live_access_secret:
            return BilibiliOpenPlatformAdapter(
                aggregator, pcfg.room_id.strip(),
                app_id=pcfg.open_live_app_id,
                access_key=pcfg.open_live_access_key,
                access_secret=pcfg.open_live_access_secret,
            )
        return BilibiliDirectAdapter(aggregator, pcfg.room_id.strip())
    cls_map = {"douyin": DouyinAdapter, "kuaishou": KuaishouAdapter}
    return cls_map[name](aggregator, pcfg.room_id.strip())


def _has_config(pcfg) -> bool:
    """Check if a platform config has enough info to start."""
    if pcfg.room_id.strip():
        return True
    if getattr(pcfg, "chat_url", "").strip():
        return True
    return False


async def sync_adapters() -> None:
    """Start/stop adapters to match current config."""
    for name in ("bilibili", "douyin", "kuaishou"):
        pcfg = config.platform(name)
        running = name in active_adapters
        has_cfg = _has_config(pcfg)

        if (not pcfg.enabled or not has_cfg) and running:
            logger.info("stopping %s adapter", name)
            await active_adapters.pop(name).stop()
            continue

        if pcfg.enabled and has_cfg and not running:
            logger.info("starting %s adapter room=%s", name, pcfg.room_id)
            adapter = _make_adapter(name, pcfg)
            active_adapters[name] = adapter
            await adapter.start()

        if pcfg.enabled and has_cfg and running:
            old = active_adapters[name]
            if old.room_id != pcfg.room_id.strip():
                logger.info("restarting %s adapter: room %s -> %s", name, old.room_id, pcfg.room_id)
                await old.stop()
                adapter = _make_adapter(name, pcfg)
                active_adapters[name] = adapter
                await adapter.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await aggregator.start()
    await sync_adapters()
    if config.token:
        logger.info("MultiDanmaku started (token-protected)")
    else:
        logger.info("MultiDanmaku started (no token set)")
    yield
    for adapter in list(active_adapters.values()):
        await adapter.stop()
    await aggregator.stop()
    logger.info("MultiDanmaku stopped")


app = FastAPI(title="MultiDanmaku", lifespan=lifespan)


# -- API endpoints (token-protected) --------------------------------------

@app.get("/api/config")
async def get_config(x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    return config.to_dict()


@app.put("/api/config")
async def update_config(request: Request, x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    from backend.config import _from_dict
    body: dict[str, Any] = await request.json()
    merged = {**config.to_dict(), **body}
    new_cfg = _from_dict(merged)
    config.bilibili = new_cfg.bilibili
    config.douyin = new_cfg.douyin
    config.kuaishou = new_cfg.kuaishou
    config.display = new_cfg.display
    config.custom_css = new_cfg.custom_css
    config.css_template = new_cfg.css_template
    config.token = new_cfg.token
    save_config(config)
    await sync_adapters()
    return config.to_dict()


@app.get("/api/status")
async def get_status(x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    return {
        "active_adapters": list(active_adapters.keys()),
        "ws_clients": len(aggregator._clients),
        "history_count": len(aggregator._history),
    }


@app.get("/api/history")
async def get_history(limit: int = 50, x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    return aggregator.get_history(limit)


@app.post("/api/history/clear")
async def clear_history(x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    aggregator.clear_history()
    return {"ok": True}


@app.post("/api/test")
async def send_test(request: Request, x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    from backend.models import EventType, LiveEvent, Platform
    body: dict[str, Any] = await request.json()
    platform = body.get("platform", "bilibili")
    username = body.get("username", "测试用户")
    content = body.get("content", "这是一条测试消息")
    try:
        plat = Platform(platform)
    except ValueError:
        plat = Platform.BILIBILI
    event = LiveEvent(
        platform=plat,
        room_id="test",
        event_type=EventType.DANMAKU,
        username=username,
        content=content,
        avatar=None,
        raw={"test": True},
    )
    aggregator.publish(event)
    return {"ok": True}


@app.get("/api/avatar")
async def proxy_avatar(url: str):
    """Proxy avatar image from Bilibili CDN (bypasses referer check)."""
    if not url.startswith("https://i0.hdslb.com/") and not url.startswith("https://i1.hdslb.com/") and not url.startswith("https://i2.hdslb.com/"):
        raise HTTPException(400, "Only Bilibili CDN URLs are allowed")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Referer": "https://live.bilibili.com/"}) as resp:
                if resp.status != 200:
                    raise HTTPException(resp.status)
                data = await resp.read()
                ct = resp.headers.get("Content-Type", "image/jpeg")
                return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})
    except aiohttp.ClientError:
        raise HTTPException(502)


UPLOAD_DIR = FRONTEND_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/api/upload")
async def upload_icon(file: UploadFile = FastAPIFile(...), x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    ext = pathlib.Path(file.filename or "icon.png").suffix or ".png"
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        raise HTTPException(400, "不支持的图片格式")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / name
    data = await file.read()
    dest.write_bytes(data)
    return {"url": f"/uploads/{name}"}


@app.post("/api/overlay")
async def open_overlay(x_token: str | None = Header(default=None)):
    _verify_token(x_token)
    from backend.overlay import launch_overlay
    try:
        launched = launch_overlay()
        return {"ok": True, "new": launched}
    except ImportError:
        raise HTTPException(500, detail="pywebview 未安装，请运行: pip install pywebview")


# -- WebSocket (open for OBS display) --------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await aggregator.add_client(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        aggregator.remove_client(ws)


# -- Frontend pages --------------------------------------------------------

@app.get("/")
async def index():
    """OBS source page — always accessible, no token required."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/app.js")
async def app_js():
    return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")


@app.get("/templates/{filename}")
async def css_template(filename: str):
    path = FRONTEND_DIR / "templates" / filename
    if path.exists() and path.suffix == ".css":
        return FileResponse(path, media_type="text/css")
    return HTMLResponse("Not Found", status_code=404)


@app.get("/admin")
async def admin_page():
    """Admin panel page — token gate handled client-side."""
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/admin.js")
async def admin_js():
    return FileResponse(FRONTEND_DIR / "admin.js", media_type="application/javascript")


@app.get("/overlay")
async def overlay_page():
    return FileResponse(FRONTEND_DIR / "overlay.html")


@app.get("/uploads/{filename}")
async def uploaded_file(filename: str):
    path = UPLOAD_DIR / filename
    if not path.exists() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        return HTMLResponse("Not Found", status_code=404)
    media_types = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    }
    return FileResponse(path, media_type=media_types.get(path.suffix.lower(), "application/octet-stream"))
