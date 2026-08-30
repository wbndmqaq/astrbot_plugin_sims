"""时装店 - 基于 fzd.json（发型/连衣裙/外套等 8 部位时装 + 套装）.

原版携带了完整的时装数据（含品质倍率与套装加成）但从未接入指令。战斗
属性（攻击/暴击等）无玩法消费，本模块取其 charm（魅力）与 mood（心情）
加成落地：购买 → 穿戴 → 魅力/心情实时加成 → 套装件数额外倍率。
"""

from __future__ import annotations

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.db import save_user
from .base import cmd

SLOT_NAMES = {
    "hair": "发型",
    "dress": "连衣裙",
    "coat": "外套",
    "top": "上衣",
    "bottom": "下装",
    "socks": "袜子",
    "shoes": "鞋子",
    "accessories": "饰品",
}
SLOT_BY_NAME = {v: k for k, v in SLOT_NAMES.items()}


def _fashion_data() -> dict:
    data = game_data._load("fashion.json")
    return data if isinstance(data, dict) else {}


def _all_fashion_items() -> list[dict]:
    """展平 clothes（accessories 为 {子类: [items]} 嵌套）。"""
    result: list[dict] = []
    clothes = _fashion_data().get("clothes") or {}
    for entries in clothes.values():
        if isinstance(entries, list):
            result.extend(entries)
        elif isinstance(entries, dict):
            for sub in entries.values():
                if isinstance(sub, list):
                    result.extend(sub)
    return result


def _quality_bonus(quality: str) -> float:
    qualities = _fashion_data().get("qualities") or {}
    quality_cfg = qualities.get(quality) or {}
    return float(quality_cfg.get("bonus", 1.0))


def _require_cd(event, action: str) -> None:
    remaining = cd_remaining(sender_id(event), "fashion", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")


async def _require_player(event) -> dict:
    from . import base as _guards

    return await _guards.require_player(event)
    from . import base as _guards


def _wardrobe(player: dict) -> list[str]:
    return player.setdefault("fashion_wardrobe", [])


def _worn(player: dict) -> dict[str, str]:
    return player.setdefault("fashion_worn", {})


def _item_bonus(item: dict) -> dict[str, int]:
    attrs = item.get("attributes") or {}
    quality = _quality_bonus(item.get("quality", "普通"))
    return {
        "charm": round(attrs.get("charm", 0) * quality),
        "mood": round(attrs.get("mood", 0) * quality),
    }


def _set_multiplier(player: dict) -> tuple[float, str]:
    """穿戴套装件数 → 魅力倍率（2件×1.1 / 4件×1.2 / 全套×1.3）。"""
    worn = _worn(player)
    if not worn:
        return 1.0, ""
    worn_ids = set(worn.values())
    for set_cfg in (_fashion_data().get("sets") or {}).values():
        pieces = set_cfg.get("pieces") or []
        count = len(worn_ids & set(pieces))
        bonus = set_cfg.get("bonus") or {}
        threshold = "full" if count >= len(pieces) and pieces else str(count)
        if threshold in bonus:
            return float(bonus[threshold].get("charm", 1.0)), set_cfg.get("name", "")
        # 取达到的最高档
        for tier in ("4", "2"):
            if count >= int(tier) and tier in bonus:
                return float(bonus[tier].get("charm", 1.0)), set_cfg.get("name", "")
    return 1.0, ""


def _total_bonus(player: dict) -> dict[str, int]:
    charm = 0
    mood = 0
    for item_id in _worn(player).values():
        item = next((i for i in _all_fashion_items() if i.get("id") == item_id), None)
        if item:
            bonus = _item_bonus(item)
            charm += bonus["charm"]
            mood += bonus["mood"]
    mult, _set_name = _set_multiplier(player)
    return {"charm": round(charm * mult), "mood": round(mood * mult)}


def _apply_bonus_delta(player: dict, delta: dict[str, int]) -> None:
    player["charm"] = max(0, int(player.get("charm", 50)) + delta.get("charm", 0))
    player["mood"] = max(
        0,
        min(100, int(player.get("mood", 100)) + delta.get("mood", 0)),
    )


def _find_item(name: str) -> dict | None:
    return next((i for i in _all_fashion_items() if i.get("name") == name), None)


@cmd(r"^#时装商店.*$", name="fashion_shop", priority=5)
async def fashion_shop(self, event):
    """浏览时装商店：#时装商店 [部位(可选)]"""
    data = _fashion_data()
    slot_name = event.get_message_str().replace("#时装商店", "").strip()
    slot = SLOT_BY_NAME.get(slot_name)
    items = _all_fashion_items()
    if slot:
        items = [i for i in items if i.get("type") == slot_name]
    if not items:
        yield "暂无时装商品！"
        return
    rows = []
    for item in items:
        bonus = _item_bonus(item)
        rows.append(
            f"[{item.get('quality')}] {item['name']}（{item.get('type')}）"
            f" - {item['price']}元\n"
            f"  魅力+{bonus['charm']} 心情+{bonus['mood']}",
        )
    set_info = ""
    for set_cfg in (data.get("sets") or {}).values():
        set_info += (
            f"\n套装【{set_cfg.get('name')}】：集齐2件魅力×1.1 / 4件×1.2 / 全套×1.3"
        )
    yield (
        "【时装商店】\n\n"
        + "\n\n".join(rows)
        + set_info
        + "\n\n使用 #购买时装 [名称] 购买，#穿戴时装 [名称] 穿戴"
    )


@cmd(r"^#购买时装.*$", name="fashion_buy", priority=9)
async def fashion_buy(self, event):
    """购买时装：#购买时装 [名称]"""
    _require_cd(event, "buy")
    user_id = sender_id(event)
    player = await _require_player(event)
    name = event.get_message_str().replace("#购买时装", "").strip()
    if not name:
        yield "格式：#购买时装 [名称]，使用 #时装商店 查看列表。"
        return
    item = _find_item(name)
    if item is None:
        yield "时装店没有这款时装！使用 #时装商店 查看。"
        return
    if item["id"] in _wardrobe(player):
        yield "你的衣柜里已经有这件时装了！"
        return
    if int(player.get("money", 0)) < item["price"]:
        yield f"金钱不足！{item['name']}需要{item['price']}元。"
        return
    player["money"] = int(player.get("money", 0)) - item["price"]
    _wardrobe(player).append(item["id"])
    await save_user(user_id, player)
    set_cd(user_id, "fashion", "buy")
    yield (
        f"购买了[{item.get('quality')}] {item['name']}！\n\n"
        "使用 #穿戴时装 "
        f"{item['name']} 穿戴（魅力+{_item_bonus(item)['charm']}）"
    )


@cmd(r"^#穿戴时装.*$", name="fashion_wear", priority=9)
async def fashion_wear(self, event):
    """穿戴时装：#穿戴时装 [名称]"""
    _require_cd(event, "wear")
    user_id = sender_id(event)
    player = await _require_player(event)
    name = event.get_message_str().replace("#穿戴时装", "").strip()
    if not name:
        yield "格式：#穿戴时装 [名称]"
        return
    item = _find_item(name)
    if item is None:
        yield "没有这款时装！"
        return
    if item["id"] not in _wardrobe(player):
        yield "你的衣柜里没有这件时装！先使用 #购买时装 购买。"
        return
    worn = _worn(player)
    slot = next(
        (s for s, sn in SLOT_NAMES.items() if item.get("type") == sn),
        item.get("type"),
    )
    total_before = _total_bonus(player)
    worn[slot] = item["id"]
    total_after = _total_bonus(player)
    _apply_bonus_delta(
        player,
        {
            "charm": total_after["charm"] - total_before["charm"],
            "mood": total_after["mood"] - total_before["mood"],
        },
    )
    await save_user(user_id, player)
    set_cd(user_id, "fashion", "wear")
    mult, set_name = _set_multiplier(player)
    yield (
        f"已穿上[{item.get('quality')}] {item['name']}！\n\n"
        f"当前时装加成：魅力+{total_after['charm']} 心情+{total_after['mood']}"
        + (f"\n套装【{set_name}】生效中（×{mult}）" if set_name else "")
    )


@cmd(r"^#脱下时装.*$", name="fashion_takeoff", priority=9)
async def fashion_takeoff(self, event):
    """脱下时装：#脱下时装 [部位]"""
    _require_cd(event, "takeoff")
    user_id = sender_id(event)
    player = await _require_player(event)
    slot_name = event.get_message_str().replace("#脱下时装", "").strip()
    slot = SLOT_BY_NAME.get(slot_name, slot_name)
    worn = _worn(player)
    if slot not in worn:
        yield f"你没有穿戴{slot_name or '该部位'}的时装！"
        return
    item = next(
        (i for i in _all_fashion_items() if i.get("id") == worn[slot]),
        None,
    )
    total_before = _total_bonus(player)
    del worn[slot]
    total_after = _total_bonus(player)
    _apply_bonus_delta(
        player,
        {
            "charm": total_after["charm"] - total_before["charm"],
            "mood": total_after["mood"] - total_before["mood"],
        },
    )
    await save_user(user_id, player)
    set_cd(user_id, "fashion", "takeoff")
    yield f"已脱下{item['name'] if item else slot_name}。"


@cmd(r"^#我的时装$", name="fashion_my", priority=5)
async def fashion_my(self, event):
    """查看衣柜、已穿时装与加成"""
    player = await _require_player(event)
    wardrobe = _wardrobe(player)
    worn = _worn(player)
    if not wardrobe:
        yield ("你的衣柜还是空的！使用 #时装商店 查看时装，#购买时装 [名称] 购买。")
        return
    all_items = _all_fashion_items()
    worn_rows = []
    for slot, item_id in worn.items():
        item = next((i for i in all_items if i.get("id") == item_id), None)
        if item:
            worn_rows.append(f"  {SLOT_NAMES.get(slot, slot)}：{item['name']}")
    total = _total_bonus(player)
    mult, set_name = _set_multiplier(player)
    rows = []
    for item_id in wardrobe:
        item = next((i for i in all_items if i.get("id") == item_id), None)
        if item:
            wearing = item_id in worn.values()
            rows.append(
                f"[{item.get('quality')}] {item['name']}（{item.get('type')}）"
                + ("【穿戴中】" if wearing else ""),
            )
    yield (
        "【我的时装】\n\n"
        + "\n".join(worn_rows)
        + f"\n\n加成合计：魅力+{total['charm']} 心情+{total['mood']}"
        + (f"（套装【{set_name}】×{mult}）" if set_name else "")
        + "\n\n衣柜：\n"
        + "\n".join(rows)
    )


@cmd(r"^#时装套装$", name="fashion_sets", priority=5)
async def fashion_sets(self, event):
    """查看套装收集进度"""
    player = await _require_player(event)
    worn = set(_worn(player).values())
    rows = []
    for set_cfg in (_fashion_data().get("sets") or {}).values():
        pieces = set_cfg.get("pieces") or []
        owned = [p for p in pieces if p in _wardrobe(player)]
        wearing = len([p for p in pieces if p in worn])
        rows.append(
            f"【{set_cfg.get('name')}】{len(owned)}/{len(pieces)} 件已拥有，"
            f"{wearing} 件穿戴中\n"
            f"  加成：2件魅力×1.1 / 4件魅力×1.2 / 全套魅力×1.3",
        )
    if not rows:
        yield "暂无套装信息！"
        return
    yield "【时装套装】\n\n" + "\n\n".join(rows)
