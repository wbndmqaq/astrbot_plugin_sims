"""成就图鉴体系：自动扫描与奖励结算。"""

from __future__ import annotations

from typing import Any

from ..db import db


async def load_achievement_state(user_id: str) -> dict[str, Any]:
    data = await db.read_kv(f"achievement_state_{user_id}", None)
    if isinstance(data, dict):
        data.setdefault("unlocked", [])
        data.setdefault("times", {})
        return data
    initial = {"unlocked": [], "times": {}}
    await db.write_kv(f"achievement_state_{user_id}", initial)
    return initial


async def save_achievement_state(user_id: str, state: dict[str, Any]) -> None:
    await db.write_kv(f"achievement_state_{user_id}", state)
