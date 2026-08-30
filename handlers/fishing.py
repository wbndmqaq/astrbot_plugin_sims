"""钓鱼系统 - port of ``apps/钓鱼系统.js``.

Two-stage fishing (cast -> bite notification -> reel), rod/bait/basket
equipment, freshness decay with a periodic basket cleanup, per-user
statistics and a global ranking board.
"""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any

from ..core import gamedata as game_data
from ..core.context import cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import check_user, get_store, save_user
from ..core.renderer import renderer
from .base import cmd

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
GUIDE_MD = PLUGIN_ROOT / "模拟人生攻略.md"


def _equipment() -> dict:
    data = game_data._load("fishing_equipment.json")
    return data if isinstance(data, dict) else {"rods": [], "baits": [], "baskets": []}


def _fish_data() -> dict:
    data = game_data._load("fish.json")
    return data if isinstance(data, dict) else {"fishes": []}


async def _init_fishing(user_id: str) -> dict[str, Any]:
    store = get_store()
    data = await store.read_kv(f"fishing_{user_id}", None)
    if isinstance(data, dict):
        return data
    return {
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


async def _save_fishing(user_id: str, data: dict) -> None:
    await get_store().write_kv(f"fishing_{user_id}", data)


async def _load_ranking() -> dict:
    data = await get_store().read_kv("fishing_ranking", {})
    return data if isinstance(data, dict) else {}


def _css_file() -> str:
    from ..core.renderer import BASE_HREF_DIR

    return BASE_HREF_DIR.as_uri() + "/"


async def _send_image(event, template: str, data: dict):
    path = await renderer.render_image(template, {"cssFile": _css_file(), **data})
    return event.image_result(path)


# ---------------------------------------------------------- 5-min cleanup --
async def update_fish_basket() -> None:
    store = get_store()
    fishes = _fish_data().get("fishes") or []
    for key, raw in (await store.read_all_kv()).items():
        if not key.startswith("fishing_") or key == "fishing_ranking":
            continue
        if not isinstance(raw, dict):
            continue
        basket = raw.get("fish_basket") or []
        kept = []
        for fish in basket:
            info = next((f for f in fishes if f.get("id") == fish.get("id")), None)
            if info and (
                time.time() * 1000 - fish.get("catchTime", 0)
            ) / 1000 <= info.get(
                "freshness",
                3600,
            ):
                kept.append(fish)
        if len(kept) != len(basket):
            raw["fish_basket"] = kept
            await store.write_kv(key, raw)


async def _fishing_tick(context) -> None:
    await update_fish_basket()


register_tick(_fishing_tick)


# ------------------------------------------------------------- commands --
@cmd(r"^#(?:开始)?钓鱼$", name="fishing_start", priority=4)
async def fishing_start(self, event):
    """开始钓鱼，等待鱼儿上钩"""
    user_id = sender_id(event)
    if await check_user(user_id) is None:
        yield "请先创建模拟人生角色！"
        return
    fishing = await _init_fishing(user_id)
    if fishing["fishing_status"] != "idle":
        yield "你已经在钓鱼了！"
        return
    remaining = cd_remaining(user_id, "fishing", "start")
    if remaining > 0:
        yield f"钓鱼太频繁啦，请等待{remaining}秒后再试～"
        return
    equipment = _equipment()
    basket_cfg = next(
        (b for b in equipment.get("baskets", []) if b["id"] == fishing["basket"]),
        None,
    )
    capacity = basket_cfg.get("capacity", 5) if basket_cfg else 5
    if len(fishing["fish_basket"]) >= capacity:
        yield "鱼篓已经满了，请先出售鱼获！"
        return

    fishing["fishing_status"] = "waiting"
    fishing["start_time"] = int(time.time() * 1000)
    await _save_fishing(user_id, fishing)
    set_cd(user_id, "fishing", "start")

    wait_seconds = random.randint(30, 59)

    async def _bite_later():
        await asyncio.sleep(wait_seconds)
        current = await _init_fishing(user_id)
        if current.get("fishing_status") == "waiting":
            current["fishing_status"] = "ready"
            await _save_fishing(user_id, current)
            try:
                await event.send(event.plain_result("鱼儿上钩了！快发送 #收杆 ！"))
            except Exception:
                pass

    asyncio.create_task(_bite_later())
    yield "你开始钓鱼了，耐心等待鱼儿上钩..."


@cmd(r"^#收杆$", name="fishing_pull", priority=4)
async def fishing_pull(self, event):
    """收杆获取渔获"""
    user_id = sender_id(event)
    fishing = await _init_fishing(user_id)
    if fishing.get("fishing_status") != "ready":
        yield "现在不是收杆的好时机！"
        return
    equipment = _equipment()
    rod = next(
        (r for r in equipment.get("rods", []) if r["id"] == fishing["rod"]), None
    )
    bait = next(
        (b for b in equipment.get("baits", []) if b["id"] == fishing["bait"]), None
    )
    success_rate = (
        (rod.get("success_rate", 50) + bait.get("attract_rate", 50)) / 2
        if rod and bait
        else 50
    )
    if random.random() * 100 <= success_rate:
        fishes = [
            f
            for f in _fish_data().get("fishes", [])
            if f.get("difficulty", 1) <= fishing.get("level", 1)
        ]
        fish = random.choice(fishes) if fishes else None
        if fish is None:
            yield "水里静悄悄的，什么也没钓到..."
        else:
            weight = fish["weight"]["min"] + random.random() * (
                fish["weight"]["max"] - fish["weight"]["min"]
            )
            weight = round(weight, 2)
            fishing["fish_basket"].append(
                {
                    "id": fish["id"],
                    "weight": weight,
                    "catchTime": int(time.time() * 1000),
                },
            )
            fishing["total_catch"] += 1
            fishing["total_weight"] = round(
                fishing["total_weight"] + weight,
                2,
            )
            fishing["exp"] += fish.get("exp", 10)
            level_up_note = ""
            if fishing["exp"] >= fishing["level"] * 100:
                fishing["level"] += 1
                fishing["exp"] = 0
                level_up_note = f"恭喜！你的钓鱼等级提升到{fishing['level']}级！"
            ranking = await _load_ranking()
            entry = ranking.setdefault(
                user_id,
                {"total_catch": 0, "total_weight": 0, "best_catch": None},
            )
            entry["total_catch"] += 1
            entry["total_weight"] = round(entry["total_weight"] + weight, 2)
            best = entry.get("best_catch")
            if not best or weight > best.get("weight", 0):
                entry["best_catch"] = {"fish_id": fish["id"], "weight": weight}
            await get_store().write_kv("fishing_ranking", ranking)
            # Reset status before reporting the catch (original semantics).
            fishing["fishing_status"] = "idle"
            fishing["start_time"] = 0
            await _save_fishing(user_id, fishing)
            yield await _send_image(
                event,
                "fishing_success",
                {"fish": fish, "weight": f"{weight:.2f}"},
            )
            if level_up_note:
                yield level_up_note
            return
    else:
        yield "可惜，鱼儿跑掉了..."
    fishing["fishing_status"] = "idle"
    fishing["start_time"] = 0
    await _save_fishing(user_id, fishing)


@cmd(r"^#升级鱼竿$", name="fishing_upgrade_rod", priority=4)
async def fishing_upgrade_rod(self, event):
    """升级鱼竿提高成功率"""
    user_id = sender_id(event)
    fishing = await _init_fishing(user_id)
    equipment = _equipment()
    rod = next(
        (r for r in equipment.get("rods", []) if r["id"] == fishing["rod"]), None
    )
    if rod is None or not rod.get("upgrade_cost"):
        yield "当前鱼竿已经是最高级了！"
        return
    user = await check_user(user_id)
    if user is None:
        yield "请先创建模拟人生角色！"
        return
    if int(user.get("money", 0)) < rod["upgrade_cost"]:
        yield f"升级费用不足！需要{rod['upgrade_cost']}金币。"
        return
    next_rod = next(
        (r for r in equipment.get("rods", []) if r.get("level") == rod["level"] + 1),
        None,
    )
    if next_rod is None:
        yield "当前鱼竿已经是最高级了！"
        return
    user["money"] = int(user.get("money", 0)) - rod["upgrade_cost"]
    fishing["rod"] = next_rod["id"]
    await save_user(user_id, user)
    await _save_fishing(user_id, fishing)
    yield f"成功升级到{next_rod['name']}！\n成功率提升到{next_rod['success_rate']}%"


@cmd(r"^#升级鱼饵$", name="fishing_upgrade_bait", priority=4)
async def fishing_upgrade_bait(self, event):
    """升级鱼饵提高吸引率"""
    user_id = sender_id(event)
    fishing = await _init_fishing(user_id)
    equipment = _equipment()
    bait = next(
        (b for b in equipment.get("baits", []) if b["id"] == fishing["bait"]), None
    )
    if bait is None or not bait.get("upgrade_cost"):
        yield "当前鱼饵已经是最高级了！"
        return
    user = await check_user(user_id)
    if user is None:
        yield "请先创建模拟人生角色！"
        return
    if int(user.get("money", 0)) < bait["upgrade_cost"]:
        yield f"升级费用不足！需要{bait['upgrade_cost']}金币。"
        return
    next_bait = next(
        (b for b in equipment.get("baits", []) if b.get("level") == bait["level"] + 1),
        None,
    )
    if next_bait is None:
        yield "当前鱼饵已经是最高级了！"
        return
    user["money"] = int(user.get("money", 0)) - bait["upgrade_cost"]
    fishing["bait"] = next_bait["id"]
    await save_user(user_id, user)
    await _save_fishing(user_id, fishing)
    yield f"成功升级到{next_bait['name']}！\n吸引率提升到{next_bait['attract_rate']}%"


@cmd(r"^#查看鱼篓$", name="fishing_basket", priority=4)
async def fishing_basket(self, event):
    """查看鱼篓中的渔获"""
    user_id = sender_id(event)
    fishing = await _init_fishing(user_id)
    yield await _send_image(
        event,
        "fish_basket",
        {
            "basket": fishing["fish_basket"],
            "fishData": _fish_data(),
            "equipment": _equipment(),
        },
    )
    yield None


@cmd(r"^#出售鱼获$", name="fishing_sell", priority=9)
async def fishing_sell(self, event):
    """出售鱼篓中全部渔获"""
    user_id = sender_id(event)
    fishing = await _init_fishing(user_id)
    if not fishing["fish_basket"]:
        yield "鱼篓是空的！"
        return
    fishes = _fish_data().get("fishes") or []
    total_price = 0
    spoiled = 0
    now_ms = time.time() * 1000
    for caught in fishing["fish_basket"]:
        info = next((f for f in fishes if f.get("id") == caught.get("id")), None)
        if info is None:
            spoiled += 1
            continue
        freshness = (now_ms - caught.get("catchTime", 0)) / 1000
        if freshness > info.get("freshness", 3600):
            spoiled += 1
            continue
        multiplier = max(0.5, 1 - freshness / info.get("freshness", 3600))
        price = info.get("basePrice", 0) * float(caught.get("weight", 0)) * multiplier
        total_price += int(price)
    user = await check_user(user_id)
    if user is None:
        yield "请先创建模拟人生角色！"
        return
    user["money"] = int(user.get("money", 0)) + total_price
    fishing["fish_basket"] = []
    await save_user(user_id, user)
    await _save_fishing(user_id, fishing)
    if spoiled > 0:
        yield f"出售完成！\n获得{total_price}金币\n有{spoiled}条鱼因为不新鲜被丢弃了。"
    else:
        yield f"出售完成！\n获得{total_price}金币"


@cmd(r"^#钓鱼排行$", name="fishing_ranking", priority=4)
async def fishing_ranking_cmd(self, event):
    """查看钓鱼排行榜"""
    yield await _send_image(
        event,
        "fishing_ranking",
        {"ranking": await _load_ranking(), "fishData": _fish_data()},
    )
    yield None


@cmd(r"^#(?:钓鱼商店|渔具商店)$", name="fishing_shop", priority=4)
async def fishing_shop(self, event):
    """浏览钓鱼装备商店"""
    yield await _send_image(event, "fishing_shop", {"equipment": _equipment()})
    yield None


@cmd(r"^#购买装备.*$", name="fishing_buy_equipment", priority=9)
async def fishing_buy_equipment(self, event):
    """购买钓鱼装备：#购买装备 [装备ID]"""
    import re

    user_id = sender_id(event)
    match = re.match(r"^#购买装备\s*(\w+)$", event.get_message_str().strip())
    if not match:
        yield "格式错误！正确格式：#购买装备 装备ID"
        return
    equipment_id = match.group(1)
    equipment = _equipment()
    item = None
    for category in ("rods", "baits", "baskets"):
        found = next(
            (i for i in equipment.get(category, []) if i.get("id") == equipment_id),
            None,
        )
        if found:
            item = found
            break
    if item is None:
        yield "未找到该装备！"
        return
    user = await check_user(user_id)
    if user is None:
        yield "请先创建模拟人生角色！"
        return
    if int(user.get("money", 0)) < item.get("price", 0):
        yield f"金币不足！需要{item['price']}金币。"
        return
    fishing = await _init_fishing(user_id)
    if equipment_id.startswith("rod_"):
        fishing["rod"] = equipment_id
    elif equipment_id.startswith("bait_"):
        fishing["bait"] = equipment_id
    elif equipment_id.startswith("basket_"):
        fishing["basket"] = equipment_id
    user["money"] = int(user.get("money", 0)) - item["price"]
    await save_user(user_id, user)
    await _save_fishing(user_id, fishing)
    yield f"成功购买{item['name']}！"


@cmd(r"^#钓鱼攻略$", name="fishing_guide", priority=4)
async def fishing_guide(self, event):
    """查看钓鱼系统攻略"""
    try:
        text = GUIDE_MD.read_text(encoding="utf-8")
    except Exception:
        text = (
            "# 钓鱼系统新手指南\n\n"
            "1. 基础操作\n"
            "   - 使用 #开始钓鱼 开始钓鱼\n"
            "   - 等待鱼儿上钩\n"
            "   - 看到提示后使用 #收杆\n\n"
            "2. 装备提升\n"
            "   - 升级鱼竿提高成功率\n"
            "   - 升级鱼饵增加上钩率\n"
            "   - 购买更大的鱼篓\n\n"
            "3. 注意事项\n"
            "   - 及时出售鱼获\n"
            "   - 注意鱼的新鲜度\n"
            "   - 合理规划钓鱼时间"
        )
    yield text
