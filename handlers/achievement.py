"""成就系统 - port of ``apps/成就系统.js``.

Config-driven achievements (defSet/achievement.yaml) with automatic unlock
checks, rewards and an achievement panel image.
"""

from __future__ import annotations

import time
from typing import Any

from ..core import config as cfg
from ..core.db import get_store, save_achievement, save_user
from ..core.renderer import renderer
from .base import cmd, require_player


async def _load_state(user_id: str) -> dict[str, Any]:
    data = await get_store().read_kv(f"achievement_state_{user_id}", None)
    if isinstance(data, dict):
        return {
            "unlocked": data.get("unlocked") or [],
            "times": data.get("times") or {},
        }
    return {"unlocked": [], "times": {}}


async def _save_state(user_id: str, state: dict[str, Any]) -> None:
    await get_store().write_kv(f"achievement_state_{user_id}", state)


async def _gather_stats(user_id: str, user_data: dict) -> dict[str, Any]:
    guide = await get_store().read_kv(f"guide_{user_id}", {}) or {}
    collab = await get_store().read_kv("careers_collab", {}) or {}
    lottery = await get_store().read_kv(f"lottery_{user_id}", {}) or {}
    collab_stats = (collab.get("stats") or {}).get(user_id) or {}
    lottery_stats = lottery.get("stats") or {}
    career = user_data.get("career") or {}
    return {
        "money": user_data.get("money") or 0,
        "level": user_data.get("level") or 1,
        "signin": user_data.get("consecutiveSignIn") or 0,
        "backpackCount": len(user_data.get("backpack") or []),
        "totalWork": career.get("totalWork") or 0,
        "careerLevel": career.get("level") or 0,
        "guideDone": 1 if guide.get("finished") else 0,
        "collabCount": collab_stats.get("collabCount") or 0,
        "chainDone": collab_stats.get("chainDone") or 0,
        "takeoverDone": collab_stats.get("takeoverDone") or 0,
        "lotteryCount": lottery_stats.get("count") or 0,
        "lotteryRare": lottery_stats.get("rare") or 0,
        "lotteryLegendary": lottery_stats.get("legendary") or 0,
    }


def _reward_brief(reward: dict | None) -> str:
    parts = []
    if reward and reward.get("money"):
        parts.append(f"金币x{reward['money']}")
    for item in (reward or {}).get("items") or []:
        parts.append(f"{item.get('name')}x{item.get('count', 1)}")
    return " ".join(parts) or "无"


async def check_unlocks(user_id: str, user_data: dict) -> dict[str, Any]:
    """Run all achievement conditions; grants rewards for new unlocks."""
    ach_list = cfg.get("achievement.list", []) or []
    state = await _load_state(user_id)
    stats = await _gather_stats(user_id, user_data)
    newly = []
    for ach in ach_list:
        if ach.get("id") in state["unlocked"]:
            continue
        stat_value = stats.get((ach.get("condition") or {}).get("stat")) or 0
        if stat_value >= (ach.get("condition") or {}).get("value", 10**18):
            state["unlocked"].append(ach["id"])
            state["times"][ach["id"]] = int(time.time() * 1000)
            newly.append(ach)
            reward = ach.get("reward") or {}
            if reward.get("money"):
                user_data["money"] = int(user_data.get("money") or 0) + reward["money"]
            for item in reward.get("items") or []:
                for _ in range(int(item.get("count", 1))):
                    user_data.setdefault("backpack", []).append(
                        {"name": item.get("name"), "type": item.get("type")},
                    )
            await save_achievement(
                user_id,
                {
                    "id": ach.get("id"),
                    "name": ach.get("name"),
                    "badge": ach.get("badge"),
                    "category": ach.get("category"),
                    "timestamp": int(time.time() * 1000),
                },
            )
    if newly:
        await save_user(user_id, user_data)
        await _save_state(user_id, state)
    return {"newly": newly, "state": state, "stats": stats}


def _build_groups(state: dict, stats: dict) -> list[dict]:
    categories = cfg.get("achievement.categories", []) or []
    ach_list = cfg.get("achievement.list", []) or []
    groups = []
    for cat in categories:
        items = []
        for ach in ach_list:
            if ach.get("category") != cat.get("id"):
                continue
            unlocked = ach.get("id") in state["unlocked"]
            target = (ach.get("condition") or {}).get("value", 1)
            current = min(
                stats.get((ach.get("condition") or {}).get("stat")) or 0, target
            )
            items.append(
                {
                    "name": ach.get("name"),
                    "desc": ach.get("desc"),
                    "badge": ach.get("badge"),
                    "unlocked": unlocked,
                    "reward": _reward_brief(ach.get("reward")),
                    "progressText": "已解锁" if unlocked else f"{current}/{target}",
                    "pct": round(current / target * 100) if target else 0,
                },
            )
        groups.append({"name": cat.get("name"), "items": items})
    return groups


async def _render_ach(event, user_data: dict, state: dict, stats: dict, title: str):
    groups = _build_groups(state, stats)
    total = len(cfg.get("achievement.list", []) or [])
    path = await renderer.render_image(
        "achievement",
        {
            "title": title,
            "userName": user_data.get("name") or str(event.get_sender_id()),
            "unlockedCount": len(state["unlocked"]),
            "total": total,
            "groups": groups,
            "hints": ["#我的成就", "#成就列表", "#抽奖"],
        },
    )
    return event.image_result(path)


async def _require_player_data(event) -> dict | None:

    return await require_player(event)


def _announce_lines(newly: list[dict]) -> str:
    lines = ["恭喜解锁新成就"]
    for ach in newly:
        lines.append(
            f"[{ach.get('badge')}] {ach.get('name')}：{ach.get('desc')}，"
            f"奖励 {_reward_brief(ach.get('reward'))}",
        )
    return "\n".join(lines)


@cmd(r"^#我的成就$", name="my_achievements", priority=5)
async def my_achievements(self, event):
    """查看我的成就徽章与进度"""
    user_data = await _require_player_data(event)
    result = await check_unlocks(str(event.get_sender_id()), user_data)
    if result["newly"]:
        yield _announce_lines(result["newly"])
    yield await _render_ach(event, user_data, result["state"], result["stats"], "我的成就")


@cmd(r"^#成就列表$", name="all_achievements", priority=5)
async def all_achievements(self, event):
    """查看全部成就图鉴"""
    user_data = await _require_player_data(event)
    result = await check_unlocks(str(event.get_sender_id()), user_data)
    if result["newly"]:
        yield _announce_lines(result["newly"])
    yield await _render_ach(event, user_data, result["state"], result["stats"], "成就图鉴")


@cmd(r"^#领取成就奖励$", name="claim_achievement_rewards", priority=5)
async def claim_achievement_rewards(self, event):
    """领取已解锁成就的奖励"""
    user_data = await _require_player_data(event)
    result = await check_unlocks(str(event.get_sender_id()), user_data)
    if not result["newly"]:
        yield "暂无新解锁的成就，继续努力吧"
        return
    yield _announce_lines(result["newly"])
