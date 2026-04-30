from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Platform(str, Enum):
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"


class EventType(str, Enum):
    DANMAKU = "danmaku"
    GIFT = "gift"
    LIKE = "like"
    ENTER = "enter"
    FOLLOW = "follow"
    SYSTEM = "system"


@dataclass(slots=True)
class LiveEvent:
    platform: Platform
    room_id: str
    event_type: EventType
    username: str
    content: str
    timestamp: float = field(default_factory=time.time)
    avatar: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "room_id": self.room_id,
            "event_type": self.event_type.value,
            "username": self.username,
            "content": self.content,
            "timestamp": self.timestamp,
            "avatar": self.avatar,
        }
