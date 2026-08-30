"""世界随机事件广播与全服 Buff 结算。"""

from __future__ import annotations

import random
import time
from typing import Any

from .. import gamedata
from ..cron import register_tick
from ..db import db

WORLD_KV = "world_event"


async def load_world_event() -> dict[str, Any] | None:
    data = await db.read_kv(WORLD_KV, None)
    return data if isinstance(data, dict) else None


async def save_world_event(record: dict) -> None:
    await db.write_kv(WORLD_KV, record)


async def check_world_event_tick(context: Any) -> None:
    events = gamedata.load_data("core/events.json") or []
    if not events or random.random() > 0.15:
        return
    ev = random.choice(events)
    record = {
        "id": ev.get("id"),
        "name": ev.get("name"),
        "desc": ev.get("desc"),
        "time": int(time.time() * 1000),
    }
    await save_world_event(record)


register_tick(check_world_event_tick)
