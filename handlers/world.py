"""世界随机事件 - 基于 core/events.json + core/effects.json.

原版定义了完整的事件 schema（天气/职业/社交/随机/特殊五类）但从未接入。
本模块将其挂载到每小时 tick：按类别概率抽取事件并应用到全体玩家，
``#小镇动态`` 可查看当前世界事件。
"""

from __future__ import annotations

import random
import time
from typing import Any

from ..core import gamedata as game_data
from ..core.cron import register_tick
from ..core.db import get_ban_until, get_store, load_all_users, save_user
from .base import cmd

WORLD_KV = "world_event"

# effects.type → 玩家档案字段
_FIELD_MAP = {
    "mood": "mood",
    "happiness": "happiness",
    "health": "life",
    "stamina": "stamina",
    "hunger": "hunger",
    "thirst": "thirst",
    "charm": "charm",
    "money": "money",
}


def _events_doc() -> dict:
    data = game_data._load("core/events.json")
    return data if isinstance(data, dict) else {}


def _resolve_value(value: Any) -> int:
    """支持 ``random:10-500`` 随机区间写法。"""
    if isinstance(value, str) and value.startswith("random:"):
        try:
            low, high = value[7:].split("-")
            return random.randint(int(low), int(high))
        except ValueError:
            return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _apply_event(player: dict, event: dict) -> list[str]:
    applied: list[str] = []
    for effect in event.get("effects") or []:
        etype = effect.get("type")
        value = _resolve_value(effect.get("value", 0))
        if etype == "career_exp":
            career = player.get("career")
            if career:
                career["exp"] = career.get("exp", 0) + value
                applied.append(f"职业经验{value:+d}")
            continue
        if etype == "luck":
            player["luck"] = value
            player["luck_until"] = int(time.time() * 1000) + int(
                effect.get("duration", 86400),
            )
            applied.append(f"幸运值{value:+d}")
            continue
        if etype == "inventory_remove":
            backpack = player.get("backpack") or []
            if backpack:
                removed = backpack.pop(random.randrange(len(backpack)))
                applied.append(f"丢失了{removed.get('name', '一件物品')}")
            continue
        field = _FIELD_MAP.get(etype)
        if field is None:
            continue
        current = int(player.get(field, 0) or 0)
        if field in {"money"}:
            player[field] = max(0, current + value)
        elif field in {"charm"}:
            player[field] = max(0, current + value)
        else:
            player[field] = max(0, min(100, current + value))
        applied.append(f"{field}{value:+d}")
    return applied


def roll_world_event() -> dict | None:
    """按类别概率抽取本小时的世界事件。"""
    doc = _events_doc()
    categories = doc.get("eventCategories") or {}
    events = doc.get("events") or {}
    if not events:
        return None
    picked: dict | None = None
    for _cat_id, cat_cfg in categories.items():
        if random.random() >= float(cat_cfg.get("probability", 0)):
            continue
        candidates = [
            e
            for e in events.values()
            if e.get("category") == _cat_id
            and random.random() < float(e.get("probability", 0))
        ]
        if candidates:
            picked = random.choice(candidates)
            break
    return picked


async def apply_world_event() -> dict | None:
    """抽取并应用世界事件，返回事件与影响摘要。"""
    event = roll_world_event()
    if event is None:
        await get_store().write_kv(
            WORLD_KV, {"time": int(time.time() * 1000), "event": None}
        )
        return None
    affected = 0
    sample_effects: list[str] = []
    for user_id, player in (await load_all_users()).items():
        if await get_ban_until(user_id):
            continue
        applied = _apply_event(player, event)
        if applied:
            await save_user(user_id, player)
            affected += 1
            if not sample_effects:
                sample_effects = applied
    record = {
        "time": int(time.time() * 1000),
        "event": {
            "id": event.get("id"),
            "name": event.get("name"),
            "category": event.get("category"),
            "description": event.get("description", ""),
            "effects": event.get("effects") or [],
        },
        "affected": affected,
        "sample": sample_effects,
    }
    await get_store().write_kv(WORLD_KV, record)
    return record


async def _world_tick(context) -> None:
    await apply_world_event()


register_tick(_world_tick)


@cmd(r"^#小镇动态$", name="world_status", priority=5)
async def world_status(self, event):
    """查看当前世界事件"""
    record = await get_store().read_kv(WORLD_KV, None)
    if not record or not record.get("event"):
        yield (
            "小镇风平浪静，这个小时没有特别的事件。\n世界事件每小时刷新一次，敬请期待～"
        )
        return
    event = record["event"]
    effect_names = {
        "mood": "心情",
        "happiness": "幸福",
        "health": "生命",
        "stamina": "体力",
        "hunger": "饱食",
        "thirst": "口渴",
        "charm": "魅力",
        "money": "金币",
        "career_exp": "职业经验",
        "luck": "幸运",
        "inventory_remove": "随机丢失物品",
    }
    effect_lines = []
    for effect in event.get("effects") or []:
        name = effect_names.get(effect.get("type"), effect.get("type"))
        effect_lines.append(f"  {name}: {effect.get('value')}")
    category_names = {
        "weather": "天气",
        "career": "职业",
        "social": "社交",
        "random": "随机",
        "special": "特殊",
    }
    yield (
        f"【小镇动态】{event.get('name')}"
        f"（{category_names.get(event.get('category'), event.get('category'))}）\n\n"
        f"{event.get('description', '')}\n\n"
        "效果：\n" + "\n".join(effect_lines) + "\n\n"
        f"本小时共影响 {record.get('affected', 0)} 位玩家\n"
        "世界事件每小时刷新一次"
    )
