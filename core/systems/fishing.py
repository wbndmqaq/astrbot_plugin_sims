"""钓鱼系统业务逻辑：鱼竿/鱼饵/鱼篓升级与两段式垂钓。"""

from __future__ import annotations

import time
from typing import Any

from .. import gamedata
from ..cron import register_tick
from ..db import db


async def init_fishing(user_id: str) -> dict[str, Any]:
    data = await db.read_kv(f"fishing_{user_id}", None)
    if isinstance(data, dict):
        return data
    initial = {
        "rod": "rod_01",
        "bait": "bait_01",
        "basket": "basket_01",
        "fishing_status": "idle",
        "start_time": 0,
        "fish_basket": [],
        "total_catch": 0,
        "total_weight": 0,
        "exp": 0,
        "level": 1,
    }
    return initial


async def save_fishing(user_id: str, data: dict) -> None:
    await db.write_kv(f"fishing_{user_id}", data)


async def update_fish_basket() -> None:
    fishes = (gamedata.load_data("fish.json") or {}).get("fishes") or []
    all_kv = await db.read_all_kv()
    for key, raw in all_kv.items():
        if not key.startswith("fishing_") or key == "fishing_ranking":
            continue
        if not isinstance(raw, dict):
            continue
        basket = raw.get("fish_basket") or []
        kept = []
        now = time.time() * 1000
        for fish in basket:
            info = next((f for f in fishes if f.get("id") == fish.get("id")), None)
            freshness = info.get("freshness", 3600) if info else 3600
            if (now - fish.get("catchTime", 0)) / 1000 <= freshness:
                kept.append(fish)
        if len(kept) != len(basket):
            raw["fish_basket"] = kept
            await db.write_kv(key, raw)


async def _fish_tick(context: Any) -> None:
    await update_fish_basket()


register_tick(_fish_tick)
