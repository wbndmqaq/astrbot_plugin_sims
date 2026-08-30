"""恋爱养成系统 - 基于 npcCharacters / datingShop / marriageSystem 数据.

原版插件携带了完整的 NPC / 约会 / 婚姻数据但从未接入任何指令，本模块
将其实现为完整玩法：邂逅 NPC → 送礼/约会提升好感 → 求婚订婚 → 举办
婚礼。关系数据保存在玩家存档的 ``relationship`` 字段中。
"""

from __future__ import annotations

import random
import time
from typing import Any

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.db import save_user
from .base import cmd


def _npcs() -> list[dict]:
    data = game_data._load("npcCharacters.json")
    if isinstance(data, dict):
        return data.get("characters") or []
    return []


def _dating_cfg() -> dict:
    data = game_data._load("datingShop.json")
    return data if isinstance(data, dict) else {}


def _marriage_cfg() -> dict:
    data = game_data._load("marriageSystem.json")
    return data if isinstance(data, dict) else {}


def _rel(player: dict) -> dict[str, Any]:
    return player.setdefault("relationship", {})


def _require_cd(event, action: str) -> None:
    remaining = cd_remaining(sender_id(event), "love", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")


async def _require_player(event) -> dict:
    from . import base as _guards

    return await _guards.require_player(event)
    from . import base as _guards


def _affection_cap(level: int) -> int:
    return 100


@cmd(r"^#邂逅$", name="love_meet", priority=5)
async def love_meet(self, event):
    """邂逅一位小镇居民，开始一段缘分"""
    _require_cd(event, "meet")
    user_id = sender_id(event)
    player = await _require_player(event)
    rel = _rel(player)
    if rel.get("npc_id"):
        npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
        name = npc["name"] if npc else rel["npc_id"]
        yield f"你正在与{name}交往中，专一点嘛！使用 #伴侣信息 查看关系。"
        return
    npc = random.choice(_npcs())
    rel.update(
        {
            "npc_id": npc["id"],
            "affection": int(npc.get("initialAffection", 0)),
            "status": "pursuing",
            "dating_days": 0,
            "started_at": int(time.time() * 1000),
            "married": False,
            "ceremony": None,
        },
    )
    await save_user(user_id, player)
    set_cd(user_id, "love", "meet")
    yield (
        f"你在小镇的街角邂逅了{npc['name']}（{npc.get('gender')}，{npc.get('age')}岁）\n\n"
        f"性格：{npc.get('personality')}\n\n"
        f"{npc.get('description', '')}\n\n"
        f"喜好：{'、'.join(npc.get('likes') or [])}\n\n"
        "送礼和约会可以提升好感度，使用 #送礼 [礼物名] 或 #约会 [约会名]"
    )


@cmd(r"^#送礼.*$", name="love_gift", priority=9)
async def love_gift(self, event):
    """给心仪的 TA 送礼：#送礼 [礼物名]"""
    _require_cd(event, "gift")
    user_id = sender_id(event)
    player = await _require_player(event)
    rel = _rel(player)
    if not rel.get("npc_id"):
        yield "你还没有心仪的对象！使用 #邂逅 开始一段缘分。"
        return
    gift_name = event.get_message_str().replace("#送礼", "").strip()
    gifts = _dating_cfg().get("gifts") or []
    if not gift_name:
        rows = [f"{g['name']} - {g['price']}元 (好感+{g['affection']})" for g in gifts]
        yield "可选礼物：\n\n" + "\n\n".join(rows) + "\n\n使用 #送礼 [礼物名]"
        return
    gift = next((g for g in gifts if g["name"] == gift_name), None)
    if gift is None:
        yield "没有这种礼物！使用 #送礼 查看礼物列表。"
        return
    if int(player.get("money", 0)) < gift["price"]:
        yield f"金钱不足！{gift['name']}需要{gift['price']}元。"
        return
    player["money"] = int(player.get("money", 0)) - gift["price"]

    npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
    bonus = 1
    note = ""
    if npc and gift_name in (npc.get("likes") or []):
        bonus = 2
        note = f"\n\n{npc['name']}很喜欢这份礼物，好感加成翻倍！"

    if rel.get("married"):
        yield "你们已经结婚了，依然可以送礼物表达爱意～"
        return

    rel["affection"] = min(
        _affection_cap(rel.get("affection", 0)) * 2,
        rel.get("affection", 0) + gift["affection"] * bonus,
    )
    await save_user(user_id, player)
    set_cd(user_id, "love", "gift")
    yield (
        f"你把{gift['name']}送给了{npc['name'] if npc else 'TA'}，"
        f"花费{gift['price']}元\n\n"
        f"好感度 +{gift['affection'] * bonus}（当前 {rel['affection']}）{note}"
    )


@cmd(r"^#约会.*$", name="love_date", priority=9)
async def love_date(self, event):
    """约 TA 出来约会：#约会 [约会名]"""
    _require_cd(event, "date")
    user_id = sender_id(event)
    player = await _require_player(event)
    rel = _rel(player)
    if not rel.get("npc_id"):
        yield "你还没有心仪的对象！使用 #邂逅 开始一段缘分。"
        return
    if rel.get("married"):
        yield "你们已经结婚了，随时都可以约会，不用预约啦～"
        return
    dates = _dating_cfg().get("dates") or []
    date_name = event.get_message_str().replace("#约会", "").strip()
    if not date_name:
        rows = [
            f"{d['name']} - {d['price']}元 (好感+{d['affection']}, {d.get('duration', 2)}小时)"
            for d in dates
        ]
        yield "可选约会：\n\n" + "\n\n".join(rows) + "\n\n使用 #约会 [约会名]"
        return
    date_opt = next((d for d in dates if d["name"] == date_name), None)
    if date_opt is None:
        yield "没有这种约会项目！使用 #约会 查看列表。"
        return
    cost = date_opt["price"]
    if int(player.get("money", 0)) < cost:
        yield f"金钱不足！{date_opt['name']}需要{cost}元。"
        return
    if int(player.get("stamina", 0)) < 10:
        yield "体力不足！约会也是个体力活（需要10点体力）。"
        return
    player["money"] = int(player.get("money", 0)) - cost
    player["stamina"] = max(0, int(player.get("stamina", 0)) - 10)

    npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
    rel["affection"] = min(
        200,
        rel.get("affection", 0) + date_opt["affection"],
    )
    rel["dating_days"] = rel.get("dating_days", 0) + 1
    await save_user(user_id, player)
    set_cd(user_id, "love", "date")
    activities = "、".join(date_opt.get("activities") or [])
    yield (
        f"你和{npc['name'] if npc else 'TA'}在{date_opt.get('location', '')}"
        f"进行了「{date_opt['name']}」\n\n"
        f"活动：{activities}\n\n"
        f"好感度 +{date_opt['affection']}（当前 {rel['affection']}）\n\n"
        f"已交往 {rel['dating_days']} 天"
    )


@cmd(r"^#求婚.*$", name="love_propose", priority=9)
async def love_propose(self, event):
    """向 TA 求婚：#求婚 [戒指名]"""
    _require_cd(event, "propose")
    user_id = sender_id(event)
    player = await _require_player(event)
    rel = _rel(player)
    if not rel.get("npc_id"):
        yield "你还没有心仪的对象！使用 #邂逅 开始一段缘分。"
        return
    if rel.get("married") or rel.get("status") == "engaged":
        yield "你们已经（订）结婚啦！使用 #伴侣信息 查看详情。"
        return
    req = _marriage_cfg().get("requirements") or {}
    if rel.get("affection", 0) < req.get("affectionLevel", 100):
        yield (
            f"好感度不足！求婚至少需要{req.get('affectionLevel', 100)}点好感，"
            f"当前 {rel.get('affection', 0)}。多送送礼、约约会吧～"
        )
        return
    if rel.get("dating_days", 0) < req.get("minDatingDays", 7):
        yield (
            f"交往时间太短！至少需要交往{req.get('minDatingDays', 7)}天，"
            f"当前 {rel.get('dating_days', 0)} 天。"
        )
        return
    rings = _dating_cfg().get("rings") or []
    ring_name = event.get_message_str().replace("#求婚", "").strip()
    if not ring_name:
        rows = [
            f"{r['name']} - {r['price']}元 (成功率{r.get('successRate', 50)}%)"
            for r in rings
        ]
        yield (
            f"求婚条件：好感≥{req.get('affectionLevel', 100)}、"
            f"交往≥{req.get('minDatingDays', 7)}天\n\n"
            "可选戒指：\n\n" + "\n\n".join(rows) + "\n\n使用 #求婚 [戒指名]"
        )
        return
    ring = next((r for r in rings if r["name"] == ring_name), None)
    if ring is None:
        yield "没有这种戒指！使用 #求婚 查看戒指列表。"
        return
    if int(player.get("money", 0)) < ring["price"]:
        yield f"金钱不足！{ring['name']}需要{ring['price']}元。"
        return
    player["money"] = int(player.get("money", 0)) - ring["price"]
    npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
    if random.random() * 100 < ring.get("successRate", 50):
        rel["status"] = "engaged"
        rel["ring"] = ring["name"]
        await save_user(user_id, player)
        set_cd(user_id, "love", "propose")
        yield (
            f"🎉 {npc['name'] if npc else 'TA'}答应了你的求婚！\n\n"
            f"戒指：{ring['name']}\n\n"
            "现在可以举办婚礼了：#举办婚礼 [档次]\n"
            f"婚礼档次：basic({(_marriage_cfg().get('ceremony') or {}).get('basic', {}).get('price')}元) / "
            f"standard({(_marriage_cfg().get('ceremony') or {}).get('standard', {}).get('price')}元) / "
            f"luxury({(_marriage_cfg().get('ceremony') or {}).get('luxury', {}).get('price')}元)"
        )
    else:
        rel["affection"] = max(0, rel.get("affection", 0) - 10)
        await save_user(user_id, player)
        set_cd(user_id, "love", "propose")
        yield (
            f"{npc['name'] if npc else 'TA'}婉拒了你的求婚……好感度 -10\n\n"
            "别灰心，继续提升好感后再试一次！"
        )


@cmd(r"^#举办婚礼.*$", name="love_wedding", priority=9)
async def love_wedding(self, event):
    """举办婚礼：#举办婚礼 [basic/standard/luxury]"""
    _require_cd(event, "wedding")
    user_id = sender_id(event)
    player = await _require_player(event)
    rel = _rel(player)
    if rel.get("married"):
        yield "你们已经举办过婚礼了！祝百年好合～"
        return
    if rel.get("status") != "engaged":
        yield "你们还没有订婚！先使用 #求婚 [戒指名] 成功求婚。"
        return
    ceremony_cfg = _marriage_cfg().get("ceremony") or {}
    tier = event.get_message_str().replace("#举办婚礼", "").strip().lower() or "basic"
    ceremony = ceremony_cfg.get(tier)
    if ceremony is None:
        yield "婚礼档次：basic（简单）/ standard（标准）/ luxury（豪华）"
        return
    if int(player.get("money", 0)) < ceremony["price"]:
        yield f"金钱不足！{ceremony['name']}需要{ceremony['price']}元。"
        return
    player["money"] = int(player.get("money", 0)) - ceremony["price"]
    player["happiness"] = min(
        100,
        int(player.get("happiness", 100)) + ceremony.get("happiness", 10),
    )
    rel["married"] = True
    rel["status"] = "married"
    rel["ceremony"] = ceremony["name"]
    await save_user(user_id, player)
    set_cd(user_id, "love", "wedding")
    npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
    yield (
        f"💒 恭喜！你和{npc['name'] if npc else 'TA'}的{ceremony['name']}圆满礼成！\n\n"
        f"花费：{ceremony['price']}元\n\n"
        f"幸福度 +{ceremony.get('happiness', 10)}\n\n"
        "已婚福利：每日签到幸福度额外提升！"
    )


@cmd(r"^#伴侣信息$", name="love_partner_info", priority=5)
async def love_partner_info(self, event):
    """查看当前恋爱/婚姻关系"""
    player = await _require_player(event)
    rel = _rel(player)
    if not rel.get("npc_id"):
        yield "你还是单身！使用 #邂逅 开始一段缘分。"
        return
    npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
    if npc is None:
        yield "关系数据异常，请使用 #分手 结束当前关系后重新 #邂逅。"
        return
    status_map = {
        "pursuing": "热恋中",
        "engaged": "已订婚",
        "married": "已婚",
    }
    yield (
        f"【伴侣信息】\n\n"
        f"伴侣：{npc['name']}（{npc.get('gender')}，{npc.get('age')}岁）\n\n"
        f"性格：{npc.get('personality')}\n\n"
        f"喜好：{'、'.join(npc.get('likes') or [])}\n\n"
        f"反感：{'、'.join(npc.get('dislikes') or [])}\n\n"
        f"好感度：{rel.get('affection', 0)}\n\n"
        f"交往天数：{rel.get('dating_days', 0)}\n\n"
        f"关系：{status_map.get(rel.get('status'), rel.get('status'))}"
        + (f"\n\n戒指：{rel['ring']}" if rel.get("ring") else "")
        + (f"\n\n婚礼：{rel['ceremony']}" if rel.get("ceremony") else "")
    )


@cmd(r"^#分手$", name="love_breakup", priority=5)
async def love_breakup(self, event):
    """结束当前恋爱关系"""
    user_id = sender_id(event)
    player = await _require_player(event)
    rel = _rel(player)
    if not rel.get("npc_id"):
        yield "你本来就是单身！"
        return
    npc = next((n for n in _npcs() if n["id"] == rel["npc_id"]), None)
    name = npc["name"] if npc else "TA"
    player["relationship"] = {}
    await save_user(user_id, player)
    yield f"你和{name}和平分手了。缘分尽了可以再 #邂逅 新的缘分。"
