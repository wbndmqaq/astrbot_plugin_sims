"""统一商店系统 - port of ``apps/shops/index.js`` (ShopSystem).

Commands: 商店列表 / 进入商店 / 购买 / 出售 / 背包 / 使用 / 装备 / 卸下 /
查看装备 / 商品搜索
"""

from __future__ import annotations

from datetime import datetime

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.db import save_user as save
from .base import cmd, require_player

SLOT_NAMES = {
    "upper": "上装",
    "lower": "下装",
    "full": "全身",
    "feet": "鞋子",
    "outer": "外套",
    "misc": "其他",
}


async def _shop_check(event, action: str) -> dict:
    remaining = cd_remaining(sender_id(event), "shop", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")
    return await require_player(event)


def _shop_is_open(shop: dict) -> bool:
    hours = shop.get("openHours") or [0, 24]
    hour = datetime.now().hour
    start, end = int(hours[0]), int(hours[1])
    if start <= end:
        return start <= hour < end
    # 跨零点营业，例如 [18, 4]
    return hour >= start or hour < end


@cmd(r"^#(?:商店列表|模拟人生商店|商店)$", name="list_shops", priority=6)
async def list_shops(self, event):
    """查看所有商店与营业状态"""
    shops = game_data.get_shops()
    if not shops:
        yield "商店数据加载失败！"
        return
    lines = []
    for shop in (shops.get("shops") or {}).values():
        type_info = (shops.get("shopTypes") or {}).get(shop.get("type")) or {}
        icon = type_info.get("icon", "")
        is_open = _shop_is_open(shop)
        status = "营业中" if is_open else "休息中"
        lines.append(f"{icon} {shop['name']} {status}\n  {shop.get('description', '')}")
    yield (
        "商店列表\n\n━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(lines)
        + "\n\n━━━━━━━━━━━━━━━\n\n使用 #进入商店 [商店名] 进入商店"
    )


@cmd(r"^#进入商店.*$", name="enter_shop", priority=6)
async def enter_shop(self, event):
    """进入指定商店浏览商品"""
    await _shop_check(event, "enter")
    shop_name = event.get_message_str().replace("#进入商店", "").strip()
    shops = game_data.get_shops()
    shop = next(
        (s for s in (shops.get("shops") or {}).values() if s.get("name") == shop_name),
        None,
    )
    if shop is None:
        yield "未找到该商店！使用 #商店列表 查看可用商店"
        return
    if not _shop_is_open(shop):
        hours = shop.get("openHours") or [0, 24]
        yield f"该商店当前休息中，营业时间：{hours[0]}:00-{hours[1]}:00"
        return
    rows = []
    for item in shop.get("items") or []:
        item_data = game_data.get_item(item.get("itemId"))
        if not item_data:
            continue
        stock = "∞" if item.get("stock") == -1 else item.get("stock")
        rows.append(
            f"{item_data.get('icon', '')} {item_data['name']} - {item.get('price')}元"
            f" (库存:{stock})\n  {item_data.get('description', '')}",
        )
    yield (
        f"{shop['name']}\n\n店主：{shop.get('npc', '')}\n\n"
        "━━━━━━━━━━━━━━━\n\n"
        + ("\n\n".join(rows) or "暂无商品")
        + "\n\n━━━━━━━━━━━━━━━\n\n使用 #购买 [商品名] [数量] 购买商品"
    )


def _find_shop_item(item_name: str) -> tuple[dict, str] | tuple[None, None]:
    for sid, shop in (game_data.get_shops().get("shops") or {}).items():
        for item in shop.get("items") or []:
            item_data = game_data.get_item(item.get("itemId"))
            if item_data and item_data.get("name") == item_name:
                return item, sid
    return None, None


@cmd(r"^#购买.*$", name="shop_buy_item", priority=6)
async def shop_buy_item(self, event):
    """从商店购买商品：#购买 [商品名] [数量]"""
    data = await _shop_check(event, "buy")
    user_id = sender_id(event)
    params = event.get_message_str().replace("#购买", "").strip().split()
    if not params:
        raise CommandError("格式：#购买 [商品名] [数量]")
    item_name = params[0]
    try:
        quantity = int(params[1]) if len(params) > 1 else 1
    except ValueError:
        quantity = 1

    found_item, shop_id = _find_shop_item(item_name)
    if found_item is None:
        yield "未找到该商品！"
        return
    item_data = game_data.get_item(found_item["itemId"])
    total_price = int(found_item["price"]) * quantity

    if int(data.get("money", 0)) < total_price:
        yield f"资金不足！需要{total_price}元"
        return
    if found_item.get("stock") not in (None, -1) and found_item["stock"] < quantity:
        yield f"库存不足！剩余{found_item['stock']}个"
        return

    data["money"] = int(data.get("money", 0)) - total_price
    inventory = data.setdefault("inventory", {})
    inventory[found_item["itemId"]] = inventory.get(found_item["itemId"], 0) + quantity

    if found_item.get("stock") not in (None, -1):
        shops = game_data.get_shops()
        shop_items = shops["shops"][shop_id]["items"]
        for entry in shop_items:
            if entry.get("itemId") == found_item["itemId"]:
                entry["stock"] -= quantity
                break
        game_data.save_shops(shops)

    await save(user_id, data)
    set_cd(user_id, "shop", "buy")
    yield (
        f"购买成功！\n\n商品：{item_data['name']}\n\n数量：{quantity}\n\n"
        f"总价：{total_price}元\n\n剩余资金：{data['money']}元"
    )


@cmd(r"^#出售.*$", name="shop_sell_item", priority=6)
async def shop_sell_item(self, event):
    """出售背包中的物品：#出售 [物品名] [数量]"""
    data = await _shop_check(event, "sell")
    user_id = sender_id(event)
    params = event.get_message_str().replace("#出售", "").strip().split()
    if not params:
        raise CommandError("格式：#出售 [物品名] [数量]")
    item_name = params[0]
    try:
        quantity = int(params[1]) if len(params) > 1 else 1
    except ValueError:
        quantity = 1
    quantity = max(1, quantity)

    inventory = data.get("inventory") or {}
    item_id = next(
        (
            iid
            for iid, count in inventory.items()
            if (game_data.get_item(iid) or {}).get("name") == item_name and count > 0
        ),
        None,
    )
    if item_id is None:
        yield "你没有该物品！"
        return
    item_data = game_data.get_item(item_id)
    quantity = min(quantity, inventory[item_id])
    earn = int(item_data.get("sellPrice", 0)) * quantity
    if earn <= 0:
        yield "该物品无法出售！"
        return

    inventory[item_id] -= quantity
    if inventory[item_id] <= 0:
        del inventory[item_id]
    data["money"] = int(data.get("money", 0)) + earn
    await save(user_id, data)
    set_cd(user_id, "shop", "sell")
    yield (
        f"出售成功！\n\n商品：{item_data['name']}\n\n数量：{quantity}\n\n"
        f"获得：{earn}元\n\n剩余资金：{data['money']}元"
    )


@cmd(r"^#背包$", name="show_inventory", priority=6)
async def show_inventory(self, event):
    """查看统一背包（inventory 物品）"""
    data = await _shop_check(event, "inventory")
    inventory = data.get("inventory") or {}
    if not inventory:
        yield "背包为空！使用 #进入商店 购买物品"
        return
    rows = []
    for item_id, count in inventory.items():
        item_data = game_data.get_item(item_id)
        if item_data:
            rows.append(f"{item_data.get('icon', '')} {item_data['name']} x{count}")
    yield (
        "我的背包\n\n━━━━━━━━━━━━━━━\n\n"
        + "\n".join(rows)
        + "\n\n━━━━━━━━━━━━━━━\n\n使用 #使用 [物品名] 或 #装备 [物品名]"
    )


def _find_inventory_entry(data: dict, item_name: str) -> tuple[str, int] | None:
    for item_id, count in (data.get("inventory") or {}).items():
        item_data = game_data.get_item(item_id)
        if item_data and item_data.get("name") == item_name and count > 0:
            return item_id, count
    return None


EFFECT_FIELD = {
    "health": "life",
    "hunger": "hunger",
    "thirst": "thirst",
    "mood": "mood",
    "stamina": "stamina",
}
EFFECT_LABEL = {
    "health": "生命值",
    "hunger": "饱食度",
    "thirst": "口渴度",
    "mood": "心情",
    "stamina": "体力",
}


@cmd(r"^#使用.*$", name="use_item", priority=6)
async def use_item(self, event):
    """使用背包中的消耗品"""
    data = await _shop_check(event, "use")
    user_id = sender_id(event)
    item_name = event.get_message_str().replace("#使用", "").strip()
    entry = _find_inventory_entry(data, item_name)
    if entry is None:
        yield "你没有该物品！"
        return
    item_id, _count = entry
    item_data = game_data.get_item(item_id)
    if not item_data.get("usable"):
        yield "该物品无法使用！"
        return

    effect_msgs = []
    for effect in item_data.get("effects") or []:
        effect_type = effect.get("type")
        value = int(effect.get("value", 0))
        field = EFFECT_FIELD.get(effect_type)
        if field is None:
            continue
        current = int(data.get(field, 0) or 0)
        data[field] = min(100, current + value)
        effect_msgs.append(f"{EFFECT_LABEL[effect_type]}+{value}")

    inventory = data.setdefault("inventory", {})
    inventory[item_id] -= 1
    if inventory[item_id] <= 0:
        del inventory[item_id]

    await save(user_id, data)
    set_cd(user_id, "shop", "use")
    yield f"使用了{item_data['name']}\n\n效果：{'、'.join(effect_msgs) or '无'}"


@cmd(r"^#装备.*$", name="equip_item", priority=6)
async def equip_item(self, event):
    """装备服饰/装备类物品"""
    data = await _shop_check(event, "equip")
    user_id = sender_id(event)
    item_name = event.get_message_str().replace("#装备", "").strip()
    entry = _find_inventory_entry(data, item_name)
    if entry is None:
        yield "你没有该物品！"
        return
    item_id, _count = entry
    item_data = game_data.get_item(item_id)
    if item_data.get("category") not in {"clothing", "equipment"}:
        yield "该物品无法装备！"
        return

    equipment = data.setdefault("equipment", {})
    slot = item_data.get("slot") or "misc"
    if equipment.get(slot):
        old_id = equipment[slot]
        inventory = data.setdefault("inventory", {})
        inventory[old_id] = inventory.get(old_id, 0) + 1
    equipment[slot] = item_id
    inventory = data.setdefault("inventory", {})
    inventory[item_id] -= 1
    if inventory[item_id] <= 0:
        del inventory[item_id]

    await save(user_id, data)
    set_cd(user_id, "shop", "equip")
    yield f"已装备{item_data['name']}"


@cmd(r"^#卸下.*$", name="unequip_item", priority=6)
async def unequip_item(self, event):
    """卸下已装备的物品"""
    data = await _shop_check(event, "unequip")
    user_id = sender_id(event)
    slot_name = event.get_message_str().replace("#卸下", "").strip()
    equipment = data.get("equipment") or {}
    slot = next(
        (s for s, name in SLOT_NAMES.items() if name == slot_name),
        slot_name or "misc",
    )
    if slot not in equipment:
        yield "该部位没有装备物品！"
        return
    item_id = equipment.pop(slot)
    inventory = data.setdefault("inventory", {})
    inventory[item_id] = inventory.get(item_id, 0) + 1
    await save(user_id, data)
    set_cd(user_id, "shop", "unequip")
    item_data = game_data.get_item(item_id) or {}
    yield f"已卸下{item_data.get('name', item_id)}"


@cmd(r"^#查看装备$", name="show_equipment", priority=6)
async def show_equipment(self, event):
    """查看当前装备"""
    data = await _shop_check(event, "show_equip")
    equipment = data.get("equipment") or {}
    if not equipment:
        yield "当前没有装备任何物品"
        return
    rows = []
    for slot, item_id in equipment.items():
        item_data = game_data.get_item(item_id)
        if not item_data:
            continue
        slot_name = SLOT_NAMES.get(slot, slot)
        rows.append(f"{slot_name}: {item_data.get('icon', '')} {item_data['name']}")
    yield "当前装备\n\n━━━━━━━━━━━━━━━\n\n" + "\n".join(rows)


@cmd(r"^#商品搜索.*$", name="search_items", priority=6)
async def search_items(self, event):
    """按关键词搜索全部商品"""
    keyword = event.get_message_str().replace("#商品搜索", "").strip()
    if not keyword:
        yield "请输入搜索关键词！"
        return
    items = game_data.search_items(keyword)
    if not items:
        yield "未找到相关商品"
        return
    rows = [
        f"{item.get('icon', '')} {item['name']} - {item.get('basePrice', 0)}元\n  {item.get('description', '')}"
        for item in items[:10]
    ]
    yield (f'"{keyword}"的搜索结果\n\n━━━━━━━━━━━━━━━\n\n' + "\n\n".join(rows))
