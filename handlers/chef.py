"""厨师烹饪系统 - 基于 recipes / ingredients / kitchenware 数据.

原版 function.js 携带了完整的厨师函数库与数据但无指令接入，本模块实现：
购买食材 → 按菜谱烹饪（厨具提供成功率/品质加成）→ 菜品入背包可出售。
厨师职业烹饪可获得职业经验。
"""

from __future__ import annotations

import random
import time

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.db import save_user
from .base import cmd


def _recipes() -> list[dict]:
    data = game_data._load("recipes.json")
    if isinstance(data, dict):
        return data.get("recipes") or []
    return []


def _ingredients() -> list[dict]:
    data = game_data._load("ingredients.json")
    if isinstance(data, dict):
        return data.get("ingredients") or []
    return []


def _kitchenware() -> list[dict]:
    data = game_data._load("kitchenware.json")
    if isinstance(data, dict):
        return data.get("kitchenware") or []
    return []


def _require_cd(event, action: str) -> None:
    remaining = cd_remaining(sender_id(event), "chef", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")


async def _require_player(event) -> dict:
    from . import base as _guards

    return await _guards.require_player(event)
    from . import base as _guards


def _store_ingredients(player: dict) -> dict[str, int]:
    return player.setdefault("chef_ingredients", {})


def _kitchenware_of(player: dict) -> list[dict]:
    return player.setdefault("kitchenware", [])


def _best_kitchenware_bonus(player: dict) -> dict:
    """每类厨具取最优一件，汇总加成。"""
    best: dict[str, dict] = {}
    for item in _kitchenware_of(player):
        cat = item.get("category", "")
        cur = best.get(cat)
        if cur is None or item.get("effects", {}).get("successRate", 0) > cur.get(
            "effects",
            {},
        ).get("successRate", 0):
            best[cat] = item
    bonus = {"successRate": 0, "qualityBonus": 0}
    for item in best.values():
        effects = item.get("effects") or {}
        bonus["successRate"] += effects.get("successRate", 0)
        bonus["qualityBonus"] += effects.get("qualityBonus", 0)
    return bonus


@cmd(r"^#食材市场$", name="chef_market", priority=5)
async def chef_market(self, event):
    """查看食材市场"""
    rows = [
        f"{i['name']} - {i['price']}元/{i.get('unit', '份')}" for i in _ingredients()
    ]
    yield "【食材市场】\n\n" + "\n\n".join(rows) + "\n\n使用 #购买食材 [名称] [数量]"


@cmd(r"^#购买食材.*$", name="chef_buy_ingredient", priority=9)
async def chef_buy_ingredient(self, event):
    """购买食材：#购买食材 [名称] [数量]"""
    _require_cd(event, "buy")
    user_id = sender_id(event)
    player = await _require_player(event)
    parts = event.get_message_str().replace("#购买食材", "").strip().split()
    if not parts:
        yield "格式：#购买食材 [食材名] [数量(可选)]"
        return
    name = parts[0]
    try:
        amount = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        amount = 0
    if amount <= 0:
        yield "数量必须为正整数！"
        return
    ing = next((i for i in _ingredients() if i["name"] == name), None)
    if ing is None:
        yield "食材市场没有这种食材！使用 #食材市场 查看。"
        return
    total = ing["price"] * amount
    if int(player.get("money", 0)) < total:
        yield f"金钱不足！购买{amount}份{name}需要{total}元。"
        return
    player["money"] = int(player.get("money", 0)) - total
    store = _store_ingredients(player)
    store[name] = store.get(name, 0) + amount
    await save_user(user_id, player)
    set_cd(user_id, "chef", "buy")
    yield f"购买了 {amount}{ing.get('unit', '份')}{name}，花费{total}元。"


@cmd(r"^#我的食材$", name="chef_my_ingredients", priority=5)
async def chef_my_ingredients(self, event):
    """查看拥有的食材"""
    player = await _require_player(event)
    store = _store_ingredients(player)
    if not store:
        yield "你还没有食材！使用 #食材市场 采购。"
        return
    rows = [f"{name} x{count}" for name, count in store.items()]
    yield "【我的食材】\n\n" + "\n".join(rows)


@cmd(r"^#菜谱$", name="chef_recipes", priority=5)
async def chef_recipes(self, event):
    """查看全部菜谱"""
    rows = []
    for r in _recipes():
        ings = "、".join(
            f"{i.get('name')}x{i.get('amount', 1)}" for i in r.get("ingredients") or []
        )
        rows.append(
            f"【{r['name']}】{r.get('category', '')} 难度{r.get('difficulty', 1)}"
            f" | 需食材：{ings}\n"
            f"  经验+{r.get('exp', 0)} 售价约{r.get('price', 0)}元",
        )
    yield "【菜谱大全】\n\n" + "\n\n".join(rows) + "\n\n使用 #烹饪 [菜名] 下厨"


@cmd(r"^#厨具商店$", name="chef_kitchenware_shop", priority=5)
async def chef_kitchenware_shop(self, event):
    """查看厨具商店"""
    rows = [
        f"{k['name']}（{k.get('category')}）- {k['price']}元\n"
        f"  成功率+{k.get('effects', {}).get('successRate', 0)}%"
        f" 品质+{k.get('effects', {}).get('qualityBonus', 0)}"
        for k in _kitchenware()
    ]
    yield (
        "【厨具商店】\n\n"
        + "\n\n".join(rows)
        + "\n\n使用 #购买厨具 [名称]（每类厨具生效最优一件）"
    )


@cmd(r"^#购买厨具.*$", name="chef_buy_kitchenware", priority=9)
async def chef_buy_kitchenware(self, event):
    """购买厨具：#购买厨具 [名称]"""
    _require_cd(event, "buy_kw")
    user_id = sender_id(event)
    player = await _require_player(event)
    name = event.get_message_str().replace("#购买厨具", "").strip()
    if not name:
        yield "格式：#购买厨具 [厨具名]，使用 #厨具商店 查看列表。"
        return
    kw = next((k for k in _kitchenware() if k["name"] == name), None)
    if kw is None:
        yield "厨具商店没有这种厨具！使用 #厨具商店 查看。"
        return
    if int(player.get("money", 0)) < kw["price"]:
        yield f"金钱不足！{kw['name']}需要{kw['price']}元。"
        return
    player["money"] = int(player.get("money", 0)) - kw["price"]
    owned = next(
        (x for x in _kitchenware_of(player) if x.get("id") == kw["id"]),
        None,
    )
    if owned:
        owned["count"] = owned.get("count", 1) + 1
    else:
        _kitchenware_of(player).append(
            {
                "id": kw["id"],
                "name": kw["name"],
                "category": kw.get("category", ""),
                "effects": dict(kw.get("effects") or {}),
                "count": 1,
                "acquired_at": int(time.time() * 1000),
            },
        )
    await save_user(user_id, player)
    set_cd(user_id, "chef", "buy_kw")
    yield f"购买了{kw['name']}！烹饪成功率与品质将获得加成。"


@cmd(r"^#烹饪.*$", name="chef_cook", priority=9)
async def chef_cook(self, event):
    """按菜谱烹饪：#烹饪 [菜名]"""
    _require_cd(event, "cook")
    user_id = sender_id(event)
    player = await _require_player(event)
    name = event.get_message_str().replace("#烹饪", "").strip()
    if not name:
        yield "格式：#烹饪 [菜名]，使用 #菜谱 查看菜谱。"
        return
    recipe = next((r for r in _recipes() if r["name"] == name), None)
    if recipe is None:
        yield "没有这道菜！使用 #菜谱 查看菜谱。"
        return
    store = _store_ingredients(player)
    missing = []
    for ing in recipe.get("ingredients") or []:
        need = int(ing.get("amount", 1))
        if store.get(ing.get("name", ""), 0) < need:
            missing.append(f"{ing.get('name')}x{need}")
    if missing:
        yield f"食材不足！缺少：{'、'.join(missing)}。使用 #购买食材 采购。"
        return
    for ing in recipe.get("ingredients") or []:
        store[ing["name"]] -= int(ing.get("amount", 1))
        if store[ing["name"]] <= 0:
            del store[ing["name"]]

    bonus = _best_kitchenware_bonus(player)
    base_rate = 90 - (recipe.get("difficulty", 1) - 1) * 10
    success_rate = min(98, base_rate + bonus["successRate"])

    career = player.get("career") or {}
    is_chef = career.get("id") == "chef"
    if is_chef:
        success_rate = min(99, success_rate + career.get("level", 1) * 2)

    if random.random() * 100 > success_rate:
        player["money"] = int(player.get("money", 0)) - 20
        await save_user(user_id, player)
        set_cd(user_id, "chef", "cook")
        yield (
            f"烹饪{name}失败了……食材浪费，灶台还烧糊了（清理费20元）。\n"
            f"成功率{success_rate}%，提升厨艺等级或换更好的厨具试试。"
        )
        return

    quality = 1 + random.randint(0, 2) + bonus["qualityBonus"] // 5
    sell_price = int(recipe.get("price", 100) * (1 + quality * 0.15))
    player.setdefault("backpack", []).append(
        {
            "type": "dish",
            "id": recipe["id"],
            "name": recipe["name"],
            "quality": quality,
            "price": sell_price,
            "madeTime": int(time.time() * 1000),
        },
    )
    exp_gain = recipe.get("exp", 10)
    if is_chef:
        career["exp"] = career.get("exp", 0) + exp_gain
    await save_user(user_id, player)
    set_cd(user_id, "chef", "cook")
    quality_names = {1: "普通", 2: "良好", 3: "优秀", 4: "极品", 5: "传说"}
    yield (
        f"🍳 「{recipe['name']}」烹饪成功！品质：{quality_names.get(quality, quality)}\n\n"
        f"菜品已放入背包，可使用 #出售菜品 {recipe['name']} 变现（约{sell_price}元）"
        + (f"\n\n职业经验 +{exp_gain}" if is_chef else "")
    )


@cmd(r"^#出售菜品.*$", name="chef_sell_dish", priority=9)
async def chef_sell_dish(self, event):
    """出售背包中的菜品：#出售菜品 [菜名]"""
    _require_cd(event, "sell")
    user_id = sender_id(event)
    player = await _require_player(event)
    name = event.get_message_str().replace("#出售菜品", "").strip()
    if not name:
        yield "格式：#出售菜品 [菜名]"
        return
    backpack = player.setdefault("backpack", [])
    dish = next(
        (b for b in backpack if b.get("type") == "dish" and b.get("name") == name), None
    )
    if dish is None:
        yield f"背包里没有{name}！"
        return
    earn = int(dish.get("price", 100))
    backpack.remove(dish)
    player["money"] = int(player.get("money", 0)) + earn
    await save_user(user_id, player)
    set_cd(user_id, "chef", "sell")
    yield f"出售了{name}，获得{earn}元！"


@cmd(r"^#研发菜品$", name="chef_develop_recipe", priority=9)
async def chef_develop_recipe(self, event):
    """(厨师)研发新菜品，获得经验与随机成品"""
    _require_cd(event, "develop")
    user_id = sender_id(event)
    player = await _require_player(event)
    career = player.get("career") or {}
    if career.get("id") != "chef":
        yield "只有厨师才能研发菜品！"
        return
    recipes = _recipes()
    if not recipes:
        yield "菜谱库为空！"
        return
    cost = 200
    if int(player.get("money", 0)) < cost:
        yield f"研发需要{cost}元采购试验食材，金钱不足！"
        return
    player["money"] = int(player.get("money", 0)) - cost
    recipe = random.choice(recipes)
    success_rate = min(95, 60 + career.get("level", 1) * 4)
    if random.random() * 100 > success_rate:
        career["exp"] = career.get("exp", 0) + 10
        await save_user(user_id, player)
        set_cd(user_id, "chef", "develop")
        yield (
            f"「{recipe['name']}」的改良配方试验失败……但积累了宝贵经验。\n\n"
            f"职业经验 +10（成功率 {success_rate}%）"
        )
        return
    quality = random.randint(3, 5)
    sell_price = int(recipe.get("price", 100) * (1 + quality * 0.2))
    player.setdefault("backpack", []).append(
        {
            "type": "dish",
            "id": recipe["id"],
            "name": f"秘制·{recipe['name']}",
            "quality": quality,
            "price": sell_price,
            "madeTime": int(time.time() * 1000),
        },
    )
    exp_gain = recipe.get("exp", 10) * 2
    career["exp"] = career.get("exp", 0) + exp_gain
    await save_user(user_id, player)
    set_cd(user_id, "chef", "develop")
    quality_names = {3: "优秀", 4: "极品", 5: "传说"}
    yield (
        f"🌟 研发成功！新品「秘制·{recipe['name']}」问世！\n\n"
        f"品质：{quality_names.get(quality, quality)} | 价值约{sell_price}元\n\n"
        f"菜品已放入背包，职业经验 +{exp_gain}\n\n"
        f"（研发成功率 {success_rate}%）"
    )
