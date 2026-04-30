from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any


CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config.json"


@dataclass
class PlatformDisplay:
    visible: bool = True
    label: str = ""
    color: str = ""
    icon_url: str = ""


@dataclass
class PlatformConfig:
    enabled: bool = False
    room_id: str = ""
    display: PlatformDisplay = field(default_factory=PlatformDisplay)
    open_live_app_id: str = ""
    open_live_access_key: str = ""
    open_live_access_secret: str = ""
    chat_url: str = ""


@dataclass
class DisplayConfig:
    max_messages: int = 200
    scroll_direction: str = "up"  # "up" or "down"
    fade_old: bool = False
    show_platform_badge: bool = True
    show_timestamp: bool = False
    filter_keywords: list[str] = field(default_factory=list)
    blacklist_users: list[str] = field(default_factory=list)
    min_content_length: int = 0


def _default_platform(name: str) -> PlatformConfig:
    defaults = {
        "bilibili": PlatformDisplay(label="B站", color="#00a1d6"),
        "douyin": PlatformDisplay(label="抖音", color="#fe2c55"),
        "kuaishou": PlatformDisplay(label="快手", color="#ff6600"),
    }
    return PlatformConfig(display=defaults.get(name, PlatformDisplay()))


@dataclass
class AppConfig:
    bilibili: PlatformConfig = field(default_factory=lambda: _default_platform("bilibili"))
    douyin: PlatformConfig = field(default_factory=lambda: _default_platform("douyin"))
    kuaishou: PlatformConfig = field(default_factory=lambda: _default_platform("kuaishou"))
    display: DisplayConfig = field(default_factory=DisplayConfig)
    custom_css: str = ""
    css_template: str = "default"
    token: str = ""

    def platform(self, name: str) -> PlatformConfig:
        return getattr(self, name)

    def _platform_dict(self, pcfg: PlatformConfig) -> dict[str, Any]:
        return {
            "enabled": pcfg.enabled,
            "room_id": pcfg.room_id,
            "display": {
                "visible": pcfg.display.visible,
                "label": pcfg.display.label,
                "color": pcfg.display.color,
                "icon_url": pcfg.display.icon_url,
            },
            "open_live_app_id": pcfg.open_live_app_id,
            "open_live_access_key": pcfg.open_live_access_key,
            "open_live_access_secret": pcfg.open_live_access_secret,
            "chat_url": pcfg.chat_url,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "bilibili": self._platform_dict(self.bilibili),
            "douyin": self._platform_dict(self.douyin),
            "kuaishou": self._platform_dict(self.kuaishou),
            "display": {
                "max_messages": self.display.max_messages,
                "scroll_direction": self.display.scroll_direction,
                "fade_old": self.display.fade_old,
                "show_platform_badge": self.display.show_platform_badge,
                "show_timestamp": self.display.show_timestamp,
                "filter_keywords": self.display.filter_keywords,
                "blacklist_users": self.display.blacklist_users,
                "min_content_length": self.display.min_content_length,
            },
            "custom_css": self.custom_css,
            "css_template": self.css_template,
            "token": self.token,
        }


def _merge(data: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    for k, v in data.items():
        if k in merged and isinstance(v, dict) and isinstance(merged[k], dict):
            merged[k] = _merge(v, merged[k])
        else:
            merged[k] = v
    return merged


def _parse_platform(data: dict[str, Any]) -> PlatformConfig:
    display_data = data.get("display") or {}
    return PlatformConfig(
        enabled=data.get("enabled", False),
        room_id=data.get("room_id", ""),
        display=PlatformDisplay(**display_data),
        open_live_app_id=data.get("open_live_app_id", ""),
        open_live_access_key=data.get("open_live_access_key", ""),
        open_live_access_secret=data.get("open_live_access_secret", ""),
        chat_url=data.get("chat_url", ""),
    )


def _from_dict(data: dict[str, Any]) -> AppConfig:
    defaults = AppConfig().to_dict()
    d = _merge(data, defaults)
    cfg = AppConfig()
    cfg.bilibili = _parse_platform(d["bilibili"])
    cfg.douyin = _parse_platform(d["douyin"])
    cfg.kuaishou = _parse_platform(d["kuaishou"])
    cfg.display = DisplayConfig(**d["display"])
    cfg.custom_css = d.get("custom_css", "")
    cfg.css_template = d.get("css_template", "default")
    cfg.token = d.get("token", "")
    return cfg


def load_config() -> AppConfig:
    if CONFIG_PATH.exists():
        try:
            return _from_dict(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return AppConfig()


def save_config(cfg: AppConfig) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
