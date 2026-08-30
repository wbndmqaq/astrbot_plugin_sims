"""宠物系统 - 基于 petPool.json 的抽卡式宠物玩法.

原版携带了完整的宠物池数据（含稀有度/属性/技能）但从未接入指令，本模块
实现：抽卡获得宠物 → 喂食/玩耍提升亲密度 → 放生。宠物数据保存在玩家
存档 ``pets`` 字段。
"""

from __future__ import annotations

import random
import time

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.db import save_user
from .base import cmd


def _pools() -> list[dict]:
    data = game_data._load("petPool.json")
    if isinstance(data, dict):
        return data.get("pools") or []
    return []


def _require_cd(event, action: str) -> None:
    remaining = cd_remaining(sender_id(event), "pet", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")


async def _require_player(event) -> dict:
    from . import base as _guards

    return await _guards.require_player(event)
    from . import base as _guards


def _pets(player: dict) -> list[dict]:
    return player.setdefault("pets", [])


def _pick_pet(pool: dict) -> dict:
    pets = pool.get("pets") or []
    total = sum(p.get("rate", 1) for p in pets) or 1
    roll = random.random() * total
    for pet in pets:
        roll -= pet.get("rate", 1)
        if roll <= 0:
            return pet
    return pets[-1]


@cmd(r"^#宠物商店$", name="pet_shop", priority=5)
async def pet_shop(self, event):
    """查看宠物抽卡池"""
    pools = _pools()
    rows = []
    for pool in pools:
        pet_names = "、".join(p.get("name", "") for p in pool.get("pets") or [])
        rows.append(
            f"【{pool.get('name')}】{pool.get('price')}金币/抽\n"
            f"  {pool.get('description', '')}\n"
            f"  可获得：{pet_names}",
        )
    yield (
        "【宠物商店】\n\n" + "\n\n".join(rows) + "\n\n使用 #宠物抽卡 [池名] 抽取宠物"
    )


@cmd(r"^#宠物抽卡.*$", name="pet_draw", priority=5)
async def pet_draw(self, event):
    """抽取宠物：#宠物抽卡 [池名(可选)]"""
    _require_cd(event, "draw")
    user_id = sender_id(event)
    player = await _require_player(event)
    pools = _pools()
    if not pools:
        yield "宠物商店暂未开放！"
        return
    pool_name = event.get_message_str().replace("#宠物抽卡", "").strip()
    pool = next(
        (p for p in pools if p.get("name") == pool_name or p.get("id") == pool_name),
        pools[0],
    )
    price = int(pool.get("price", 1000))
    if int(player.get("money", 0)) < price:
        yield f"金币不足！{pool.get('name')}需要{price}金币。"
        return
    player["money"] = int(player.get("money", 0)) - price
    template = _pick_pet(pool)
    pet = {
        "id": template.get("id"),
        "name": template.get("name"),
        "rarity": template.get("rarity", "R"),
        "type": template.get("type", ""),
        "skills": list(template.get("skills") or []),
        "description": template.get("description", ""),
        "stats": dict(template.get("baseStats") or {}),
        "intimacy": 10,
        "adopted_at": int(time.time() * 1000),
    }
    _pets(player).append(pet)
    await save_user(user_id, player)
    set_cd(user_id, "pet", "draw")
    yield (
        f"🎊 恭喜获得[{pet['rarity']}] {pet['name']}（{pet['type']}）！\n\n"
        f"技能：{'、'.join(pet['skills']) or '无'}\n\n"
        f"{pet['description']}\n\n"
        f"当前拥有 {len(_pets(player))} 只宠物，使用 #我的宠物 查看"
    )


@cmd(r"^#(?:我的宠物|宠物列表)$", name="pet_list", priority=5)
async def pet_list(self, event):
    """查看自己的宠物"""
    player = await _require_player(event)
    pets = _pets(player)
    if not pets:
        yield "你还没有宠物！使用 #宠物抽卡 抽取一只吧。"
        return
    rows = []
    for i, pet in enumerate(pets):
        rows.append(
            f"{i + 1}. [{pet.get('rarity')}] {pet.get('name')}"
            f"（{pet.get('type')}）亲密 {pet.get('intimacy', 0)}",
        )
    yield "【我的宠物】\n\n" + "\n\n".join(rows)


def _get_pet(player: dict, index: int) -> dict:
    pets = _pets(player)
    if index < 0 or index >= len(pets):
        raise CommandError(
            f"宠物编号无效！当前拥有 {len(pets)} 只，使用 #我的宠物 查看。"
        )
    return pets[index]


@cmd(r"^#喂食宠物\s*(\d+)$", name="pet_feed", priority=5)
async def pet_feed(self, event):
    """喂食宠物提升亲密度：#喂食宠物 [编号]"""
    _require_cd(event, "feed")
    user_id = sender_id(event)
    player = await _require_player(event)
    import re

    match = re.match(r"^#喂食宠物\s*(\d+)$", event.get_message_str().strip())
    if not match:
        yield "格式错误！正确格式：#喂食宠物 [编号]"
        return
    pet = _get_pet(player, int(match.group(1)) - 1)
    cost = 50
    if int(player.get("money", 0)) < cost:
        yield f"喂食需要{cost}金币购买宠物粮，金钱不足！"
        return
    player["money"] = int(player.get("money", 0)) - cost
    gain = random.randint(3, 8)
    pet["intimacy"] = min(100, pet.get("intimacy", 0) + gain)
    pet["stats"] = pet.get("stats") or {}
    pet["stats"]["hunger"] = min(100, pet["stats"].get("hunger", 100) + 20)
    await save_user(user_id, player)
    set_cd(user_id, "pet", "feed")
    yield (
        f"你喂了{pet['name']}最爱的食物！\n\n亲密度 +{gain}（当前 {pet['intimacy']}）"
    )


@cmd(r"^#遛宠物\s*(\d+)$", name="pet_walk", priority=5)
async def pet_walk(self, event):
    """带宠物出门玩耍：#遛宠物 [编号]"""
    _require_cd(event, "walk")
    user_id = sender_id(event)
    player = await _require_player(event)
    import re

    match = re.match(r"^#遛宠物\s*(\d+)$", event.get_message_str().strip())
    if not match:
        yield "格式错误！正确格式：#遛宠物 [编号]"
        return
    pet = _get_pet(player, int(match.group(1)) - 1)
    if int(player.get("stamina", 0)) < 10:
        yield "体力不足！遛宠物需要10点体力。"
        return
    player["stamina"] = max(0, int(player.get("stamina", 0)) - 10)
    gain = random.randint(2, 6)
    pet["intimacy"] = min(100, pet.get("intimacy", 0) + gain)
    pet["stats"] = pet.get("stats") or {}
    pet["stats"]["mood"] = min(100, pet["stats"].get("mood", 100) + 15)
    player["happiness"] = min(100, int(player.get("happiness", 100)) + 2)
    await save_user(user_id, player)
    set_cd(user_id, "pet", "walk")
    events = [
        "在公园里撒欢",
        "追着蝴蝶跑",
        "交到了新朋友",
        "捡到了一根木棍",
        "晒了个太阳",
    ]
    yield (
        f"你带{pet['name']}出门，{random.choice(events)}！\n\n"
        f"亲密度 +{gain}（当前 {pet['intimacy']}），幸福度 +2"
    )


@cmd(r"^#放生宠物\s*(\d+)$", name="pet_release", priority=5)
async def pet_release(self, event):
    """放生宠物：#放生宠物 [编号]"""
    user_id = sender_id(event)
    player = await _require_player(event)
    import re

    match = re.match(r"^#放生宠物\s*(\d+)$", event.get_message_str().strip())
    if not match:
        yield "格式错误！正确格式：#放生宠物 [编号]"
        return
    index = int(match.group(1)) - 1
    pet = _get_pet(player, index)
    name = pet["name"]
    _pets(player).pop(index)
    await save_user(user_id, player)
    yield f"你含泪放生了{name}。愿它在野外过得更好……"
