"""抽奖系统 - port of ``apps/抽奖系统.js``.

Weight-based multi-pool gacha with rarity pity counters, ticket/money
payment, ten-draw minimum-rare guarantee, records and pool preview.
"""

from __future__ import annotations

import random
import time
from typing import Any

from ..core import config as cfg
from ..core.context import cd_remaining, sender_id, set_cd
from ..core.db import check_user, get_store, save_user
from ..core.renderer import renderer
from .base import cmd


def _rarities() -> list[dict]:
    return cfg.get("lottery.rarities", []) or []


def _rarity_rank(rarity_id: str) -> int:
    for rarity in _rarities():
        if rarity.get("id") == rarity_id:
            return rarity.get("rank", 1)
    return 1


def _rarity_name(rarity_id: str) -> str:
    for rarity in _rarities():
        if rarity.get("id") == rarity_id:
            return rarity.get("name", rarity_id)
    return rarity_id


async def _load_user(user_id: str) -> dict[str, Any]:
    data = await get_store().read_kv(f"lottery_{user_id}", None)
    state: dict[str, Any] = {
        "stats": {"count": 0, "rare": 0, "legendary": 0},
        "pity": {},
        "records": [],
    }
    if isinstance(data, dict):
        merged_stats = {**state["stats"], **(data.get("stats") or {})}
        state["stats"] = merged_stats
        state["pity"] = data.get("pity") or {}
        state["records"] = data.get("records") or []
    return state


async def _save_user_state(user_id: str, state: dict) -> None:
    await get_store().write_kv(f"lottery_{user_id}", state)


def _pool_open(pool: dict) -> dict:
    if not pool.get("limited"):
        return {"open": True}
    window = pool.get("window") or {}
    now = time.time() * 1000

    def _parse(value: str) -> float | None:
        try:
            return time.mktime(time.strptime(value, "%Y-%m-%d %H:%M")) * 1000
        except (ValueError, TypeError):
            try:
                return time.mktime(time.strptime(value, "%Y-%m-%d")) * 1000
            except (ValueError, TypeError):
                return None

    start = _parse(window.get("start")) if window.get("start") else None
    end = _parse(window.get("end")) if window.get("end") else None
    if start and now < start:
        return {"open": False, "note": f"{window['start']} 开放"}
    if end and now > end:
        return {"open": False, "note": "活动已结束"}
    return {"open": True}


def _resolve_pool(arg: str) -> dict | None:
    pools = cfg.get("lottery.pools", []) or []
    if not arg:
        return pools[0] if pools else None
    return next(
        (p for p in pools if p.get("name") == arg or p.get("id") == arg),
        None,
    )


def _pity_of(state: dict, pool_id: str) -> dict:
    pity = state.setdefault("pity", {})
    if pool_id not in pity:
        pity[pool_id] = {"rareSince": 0, "epicSince": 0, "legendarySince": 0}
    return pity[pool_id]


def _draw_one(pool: dict, pity: dict) -> dict:
    thresholds = pool.get("pity") or {}
    min_rank = 1
    if (
        thresholds.get("legendary")
        and pity["legendarySince"] >= thresholds["legendary"] - 1
    ):
        min_rank = 4
    elif thresholds.get("epic") and pity["epicSince"] >= thresholds["epic"] - 1:
        min_rank = 3
    elif thresholds.get("rare") and pity["rareSince"] >= thresholds["rare"] - 1:
        min_rank = 2
    candidates = [
        item
        for item in pool.get("items", [])
        if _rarity_rank(item.get("rarity")) >= min_rank
    ]
    if not candidates:
        candidates = pool.get("items", [])
    total_weight = sum(item.get("weight", 1) for item in candidates)
    roll = random.random() * total_weight
    picked = candidates[-1]
    for item in candidates:
        roll -= item.get("weight", 1)
        if roll <= 0:
            picked = item
            break
    rank = _rarity_rank(picked.get("rarity"))
    pity["rareSince"] = 0 if rank >= 2 else pity["rareSince"] + 1
    pity["epicSince"] = 0 if rank >= 3 else pity["epicSince"] + 1
    pity["legendarySince"] = 0 if rank >= 4 else pity["legendarySince"] + 1
    return picked


def _grant(user_data: dict, item: dict, ticket_type: str) -> None:
    grant_spec = item.get("grant") or {}
    grant_type = grant_spec.get("type")
    if grant_type == "money":
        user_data["money"] = int(user_data.get("money") or 0) + grant_spec.get(
            "value", 0
        )
    elif grant_type == "stamina":
        user_data["stamina"] = min(
            100,
            int(user_data.get("stamina") or 0) + grant_spec.get("value", 0),
        )
    elif grant_type == "ticket":
        for _ in range(grant_spec.get("count", 1)):
            user_data.setdefault("backpack", []).append(
                {"name": "抽奖券", "type": ticket_type},
            )
    elif grant_type == "item":
        for _ in range(grant_spec.get("count", 1)):
            user_data.setdefault("backpack", []).append(
                {"name": item.get("name"), "type": grant_spec.get("itemType")},
            )


async def _draw(self, event, times: int):
    if not cfg.get("lottery.enabled", True):
        return
    user_id = sender_id(event)
    cd_action = "ten" if times >= 10 else "draw"
    remaining = cd_remaining(user_id, "lottery", cd_action)
    if remaining > 0:
        yield "操作太频繁了，请稍后再试"
        return
    user = await check_user(user_id)
    if user is None:
        yield "请先发送 #开始模拟人生 创建角色"
        return
    raw = event.get_message_str().strip()
    # 兼容原版前缀：#抽奖 / #模拟人生抽奖 / #十连抽 / #模拟人生十连抽
    arg = raw
    for prefix in ("#模拟人生十连抽", "#十连抽", "#模拟人生抽奖", "#抽奖"):
        if raw.startswith(prefix):
            arg = raw[len(prefix) :].strip()
            break
    pool = _resolve_pool(arg)
    if pool is None:
        yield "奖池不存在，发送 #奖池预览 查看全部奖池"
        return
    open_state = _pool_open(pool)
    if not open_state["open"]:
        yield f"[{pool['name']}]暂未开放：{open_state['note']}"
        return

    ticket_type = cfg.get("lottery.ticketType", "lottery_ticket")
    backpack = user.setdefault("backpack", [])
    ticket_used = 0
    for _ in range(times):
        idx = next(
            (i for i, b in enumerate(backpack) if b.get("type") == ticket_type), -1
        )
        if idx == -1:
            break
        backpack.pop(idx)
        ticket_used += 1
    money_draws = times - ticket_used
    if money_draws > 0:
        cost = (
            pool.get("tenCost", 0)
            if (times >= 10 and ticket_used == 0)
            else (pool.get("cost", 0) * money_draws)
        )
    else:
        cost = 0
    if int(user.get("money", 0)) < cost:
        # refund tickets
        for _ in range(ticket_used):
            backpack.append({"name": "抽奖券", "type": ticket_type})
        yield f"金币不足，本次需要{cost}金币，当前持有{user.get('money')}金币"
        return
    user["money"] = int(user.get("money", 0)) - cost

    state = await _load_user(user_id)
    pity = _pity_of(state, pool["id"])
    results = []
    for _ in range(times):
        picked = _draw_one(pool, pity)
        results.append(picked)
        _grant(user, picked, ticket_type)
        rank = _rarity_rank(picked.get("rarity"))
        state["stats"]["count"] += 1
        if rank >= 2:
            state["stats"]["rare"] += 1
        if rank >= 4:
            state["stats"]["legendary"] += 1
    if times >= 10 and not any(_rarity_rank(r.get("rarity")) >= 2 for r in results):
        rares = [i for i in pool.get("items", []) if _rarity_rank(i.get("rarity")) >= 2]
        if rares:
            picked = random.choice(rares)
            results[-1] = picked
            _grant(user, picked, ticket_type)
            state["stats"]["rare"] += 1
            if _rarity_rank(picked.get("rarity")) >= 4:
                state["stats"]["legendary"] += 1
            pity["rareSince"] = 0
            if _rarity_rank(picked.get("rarity")) >= 3:
                pity["epicSince"] = 0
            if _rarity_rank(picked.get("rarity")) >= 4:
                pity["legendarySince"] = 0

    max_records = cfg.get("lottery.maxRecords", 50)
    state["records"].insert(
        0,
        {
            "time": int(time.time() * 1000),
            "pool": pool["name"],
            "via": "ticket"
            if ticket_used == times
            else ("mixed" if ticket_used else "money"),
            "cost": cost,
            "tickets": ticket_used,
            "items": [
                {
                    "name": r.get("name"),
                    "rarity": r.get("rarity"),
                    "rarityName": _rarity_name(r.get("rarity")),
                    "limited": bool(r.get("limitedItem")),
                }
                for r in results
            ],
        },
    )
    state["records"] = state["records"][:max_records]
    await _save_user_state(user_id, state)
    await save_user(user_id, user)
    set_cd(user_id, "lottery", cd_action)

    if ticket_used == times:
        cost_text = f"消耗抽奖券x{ticket_used}"
    elif ticket_used:
        cost_text = f"抽奖券x{ticket_used} 金币x{cost}"
    else:
        cost_text = f"金币x{cost}"
    path = await renderer.render_image(
        "lottery",
        {
            "mode": "result",
            "title": "十连抽结果" if times >= 10 else "抽奖结果",
            "poolName": pool["name"],
            "userName": user.get("name") or user_id,
            "costText": cost_text,
            "results": [
                {
                    "name": r.get("name"),
                    "rarityName": _rarity_name(r.get("rarity")),
                    "rank": _rarity_rank(r.get("rarity")),
                    "limited": bool(r.get("limitedItem")),
                }
                for r in results
            ],
            "pityText": (
                f"传说保底进度 {pity['legendarySince']}/"
                f"{(pool.get('pity') or {}).get('legendary', '-')}"
            ),
            "hints": ["#抽奖", "#十连抽", "#奖池预览", "#抽奖记录"],
        },
    )
    yield event.image_result(path)


@cmd(r"^#抽奖.*$", name="lottery_draw_one", priority=5)
async def lottery_draw_one(self, event):
    """单抽：#抽奖 [奖池名(可选)]"""
    async for out in _draw(self, event, 1):
        yield out


@cmd(r"^#模拟人生十连抽.*$", name="lottery_draw_ten", priority=5)
async def lottery_draw_ten(self, event):
    """十连抽：#模拟人生十连抽 [奖池名(可选)]"""
    async for out in _draw(self, event, 10):
        yield out


@cmd(r"^#奖池预览.*$", name="lottery_pool_preview", priority=5)
async def lottery_pool_preview(self, event):
    """查看全部奖池详情"""
    pools = cfg.get("lottery.pools", []) or []
    cards = []
    for pool in pools:
        open_state = _pool_open(pool)
        groups: dict[str, list[str]] = {}
        for item in pool.get("items") or []:
            rarity_name = _rarity_name(item.get("rarity"))
            groups.setdefault(rarity_name, []).append(
                item.get("name", "") + ("(限定)" if item.get("limitedItem") else ""),
            )
        cards.append(
            {
                "name": pool.get("name"),
                "desc": pool.get("desc", ""),
                "cost": pool.get("cost"),
                "tenCost": pool.get("tenCost"),
                "open": open_state["open"],
                "note": (
                    ("限定开放中" if pool.get("limited") else "开放中")
                    if open_state["open"]
                    else open_state.get("note", "")
                ),
                "pity": pool.get("pity"),
                "groups": [
                    {"rarityName": k, "names": "、".join(v)} for k, v in groups.items()
                ],
            },
        )
    path = await renderer.render_image(
        "lottery",
        {
            "mode": "pools",
            "title": "奖池预览",
            "userName": sender_id(event),
            "cards": cards,
            "hints": ["#抽奖", "#十连抽", "#我的保底"],
        },
    )
    yield event.image_result(path)


@cmd(r"^#抽奖记录$", name="lottery_records", priority=6)
async def lottery_records(self, event):
    """查看抽奖历史记录"""
    user_id = sender_id(event)
    state = await _load_user(user_id)
    if not state["records"]:
        yield "暂无抽奖记录，发送 #抽奖 开启第一次抽取"
        return
    lines = ["抽奖记录溯源", ""]
    for i, record in enumerate(state["records"][:15]):
        ts = time.strftime("%m-%d %H:%M", time.localtime(record["time"] / 1000))
        if record.get("via") == "ticket":
            via = "抽奖券"
        elif record.get("via") == "mixed":
            via = "混合支付"
        else:
            via = f"{record.get('cost')}金币"
        lines.append(f"{i + 1}. [{ts}] {record.get('pool')} {via}")
        items = " ".join(
            f"{it.get('name')}({it.get('rarityName')}{'限定' if it.get('limited') else ''})"
            for it in record.get("items") or []
        )
        lines.append(f"   {items}")
    lines.append("")
    lines.append(
        f"累计抽取 {state['stats']['count']} 次，"
        f"稀有及以上 {state['stats']['rare']} 次，"
        f"传说 {state['stats']['legendary']} 次",
    )
    yield "\n".join(lines)


@cmd(r"^#我的保底$", name="lottery_pity", priority=6)
async def lottery_pity(self, event):
    """查看各奖池保底进度"""
    pools = cfg.get("lottery.pools", []) or []
    state = await _load_user(sender_id(event))
    lines = ["我的保底进度", ""]
    for pool in pools:
        pity = state.get("pity", {}).get(
            pool["id"],
            {"rareSince": 0, "epicSince": 0, "legendarySince": 0},
        )
        lines.append(f"[{pool['name']}]")
        pool_pity = pool.get("pity") or {}
        if pool_pity.get("rare"):
            lines.append(f"  稀有保底 {pity['rareSince']}/{pool_pity['rare']}")
        if pool_pity.get("epic"):
            lines.append(f"  史诗保底 {pity['epicSince']}/{pool_pity['epic']}")
        if pool_pity.get("legendary"):
            lines.append(
                f"  传说保底 {pity['legendarySince']}/{pool_pity['legendary']}"
            )
    lines.append("")
    lines.append("保底规则：达到对应次数未出该稀有度时，下一抽必出")
    yield "\n".join(lines)
