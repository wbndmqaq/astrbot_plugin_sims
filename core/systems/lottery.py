"""多奖池抽奖、限定保底追踪与记录。"""

from __future__ import annotations

from typing import Any

from ..db import db

DEFAULT_POOLS = [
    {
        "id": "standard",
        "name": "常驻常新池",
        "cost": 160,
        "items": [
            {"name": "经验药水", "rarity": "normal", "weight": 60},
            {"name": "银质怀表", "rarity": "rare", "weight": 30},
            {"name": "星辰之泪", "rarity": "legendary", "weight": 10},
        ],
        "pity": {"rare": 10, "legendary": 80},
    }
]


async def load_lottery_user(user_id: str) -> dict[str, Any]:
    data = await db.read_kv(f"lottery_{user_id}", None)
    if isinstance(data, dict):
        data.setdefault("pity", {})
        data.setdefault("records", [])
        data.setdefault("stats", {})
        return data
    initial = {"pity": {}, "records": [], "stats": {}}
    await db.write_kv(f"lottery_{user_id}", initial)
    return initial


async def save_lottery_user(user_id: str, state: dict) -> None:
    await db.write_kv(f"lottery_{user_id}", state)
