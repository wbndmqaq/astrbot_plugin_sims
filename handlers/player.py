"""主角色系统 - 全异步重构版.

所有持久化调用改为 await require_player / await save / await get_store().
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from ..core.context import arg_after, rnd, sender_id, set_cd
from ..core.db import get_store, save_user
from ..core.db import save_user as save
from ..core.renderer import renderer
from ..core.systems.player import (
    SENSITIVE_WORDS,
    STAMINA_POTIONS,
    backpack_is_full,
    find_backpack_item,
    new_player_data,
)
from .base import cmd, require_cd, require_player

AVATAR_DIR = Path(__file__).resolve().parent.parent / "resources" / "HTML" / "tx"


def _css_file() -> str:
    from ..core.renderer import BASE_HREF_DIR

    return BASE_HREF_DIR.as_uri() + "/"


@cmd(r"^#开始模拟人生$", name="create_player", priority=2)
async def create_player(self, event):
    """开始模拟人生，创建属于你的角色"""
    require_cd(event, "mnrs", "create")
    user_id = sender_id(event)
    existing = await get_store().check_user(user_id)
    if existing:
        yield "你已经开始过模拟人生了！"
        return
    data = new_player_data()
    await save_user(user_id, data)
    set_cd(sender_id(event), "mnrs", "create")
    yield "欢迎来到模拟人生！数据已初始化。"


@cmd(r"^#设置性别.*$", name="set_sex", priority=2)
async def set_sex(self, event):
    """设置角色性别：#设置性别 男/女"""
    require_cd(event, "mnrs", "set_sex")
    data = await require_player(event)
    gender = arg_after(event, "#设置性别")
    if gender not in {"男", "女"}:
        yield "性别只能是 男 或 女。"
        return
    data["gender"] = gender
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "set_sex")
    yield f"你的性别已设置为: {gender}"


@cmd(r"^#模拟人生改名.*$", name="change_player_name", priority=2)
async def change_player_name(self, event):
    """修改角色名：#模拟人生改名 新名字"""
    require_cd(event, "mnrs", "rename")
    data = await require_player(event)
    new_name = arg_after(event, "#模拟人生改名")
    if not new_name:
        yield "请在指令后输入新名字，例如：#模拟人生改名 小明"
        return
    if len(new_name) > 12:
        yield "新名字的字符长度不得超过12个字符。"
        return
    all_users = await get_store().load_all_users()
    if any(user.get("name") == new_name for user in all_users.values()):
        yield "该名字已被其他玩家使用，请选择其他名字。"
        return
    data["name"] = new_name
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "rename")
    yield f"你的名字已更改为: {new_name}"


@cmd(r"^#模拟人生签到$", name="daily_gift", priority=2)
async def daily_gift(self, event):
    """每日签到领取奖励"""
    require_cd(event, "mnrs", "daily")
    data = await require_player(event)
    today = datetime.now().strftime("%Y-%m-%d")
    if data.get("lastSignInDate") == today:
        yield "你今天已经签到过了！"
        return

    consecutive_days = 1
    if data.get("lastSignInDate"):
        last_date = datetime.strptime(data["lastSignInDate"], "%Y-%m-%d").date()
        yesterday = datetime.now().date() - timedelta(days=1)
        if last_date == yesterday:
            consecutive_days = int(data.get("consecutiveSignIn", 0)) + 1
    data["consecutiveSignIn"] = consecutive_days

    base_reward = 100
    continuous_bonus = min(50 * consecutive_days, 500)
    random_bonus = rnd(50, 150)
    total_money_reward = base_reward + continuous_bonus + random_bonus
    data["money"] = int(data.get("money", 0)) + total_money_reward

    stamina_bonus = rnd(10, 30)
    data["stamina"] = min(100, int(data.get("stamina", 0)) + stamina_bonus)
    happiness_bonus = rnd(5, 15)
    data["happiness"] = min(100, int(data.get("happiness", 0)) + happiness_bonus)
    hunger_bonus = 10
    thirst_bonus = 15
    data["hunger"] = min(100, int(data.get("hunger", 0)) + hunger_bonus)
    data["thirst"] = min(100, int(data.get("thirst", 0)) + thirst_bonus)
    data["lastSignInDate"] = today
    data["dailySignIn"] = True
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "daily")

    path = await renderer.render_image(
        "daily_gift",
        {
            "cssFile": _css_file(),
            "un": data["name"],
            "cd": consecutive_days,
            "tmr": total_money_reward,
            "br": base_reward,
            "cb": continuous_bonus,
            "rb": random_bonus,
            "sb": stamina_bonus,
            "hb": happiness_bonus,
            "hgb": hunger_bonus,
            "tb": thirst_bonus,
        },
    )
    yield event.image_result(path)


@cmd(r"^#模拟人生信息$", name="show_status", priority=2)
async def show_status(self, event):
    """查看个人属性面板"""
    require_cd(event, "mnrs", "status")
    data = await require_player(event)
    set_cd(sender_id(event), "mnrs", "status")
    path = await renderer.render_image(
        "Show_status",
        {
            "cssFile": _css_file(),
            "un": data.get("name"),
            "um": data.get("money"),
            "uh": data.get("happiness"),
            "ul": data.get("life"),
            "ut": data.get("thirst"),
            "uhg": data.get("hunger"),
            "uc": data.get("charm"),
            "umd": data.get("mood"),
            "ug": data.get("gender"),
            "ud": data.get("disease") or "无",
            "uj": data.get("job") or "无",
            "ulv": data.get("level"),
            "ust": data.get("stamina"),
            "up": data.get("partnerAffection"),
            "urs": data.get("relationshipStatus"),
            "ubl": len(data.get("backpack", [])),
            "ublc": data.get("backpackCapacity"),
            "ufh": data.get("familyHappiness"),
            "uot": data.get("overdueTasks"),
            "uw": data.get("weather"),
            "utt": data.get("temperature"),
            "ua": data.get("avatar") or "default.jpg",
        },
    )
    yield event.image_result(path)


@cmd(r"^#模拟人生查看头像馆$", name="view_avatars", priority=2)
async def view_avatars(self, event):
    """查看可用头像列表"""
    require_cd(event, "mnrs", "avatar")
    data = await require_player(event)
    try:
        avatars = [
            f
            for f in sorted(os.listdir(AVATAR_DIR))
            if f.lower().endswith((".jpg", ".png", ".jpeg", ".gif"))
        ]
    except OSError:
        yield "读取头像文件夹出错，请联系管理员检查路径。"
        return
    if not avatars:
        yield "未找到任何头像文件，请联系管理员添加头像。"
        return
    set_cd(sender_id(event), "mnrs", "view_avatar")
    path = await renderer.render_image(
        "View_avatars",
        {
            "cssFile": _css_file(),
            "avatars": avatars,
            "currentAvatar": data.get("avatar") or "default.jpg",
        },
    )
    yield event.image_result(path)


@cmd(r"^#设置模拟人生头像.*$", name="set_avatar", priority=2)
async def set_avatar(self, event):
    """设置头像：#设置模拟人生头像 编号/名称"""
    require_cd(event, "mnrs", "set_avatar")
    data = await require_player(event)
    user_input = arg_after(event, "#设置模拟人生头像")
    if not user_input or "/" in user_input or "\\" in user_input or ".." in user_input:
        yield (
            "请指定头像编号或名称，例如：#设置模拟人生头像 1 或 #设置模拟人生头像 default"
        )
        return

    avatar_file = user_input
    if user_input.isdigit():
        avatar_file = f"{user_input}.jpg"
    elif user_input.isalpha() and user_input.lower() == "default":
        avatar_file = "default.jpg"
    elif not re_search_suffix(user_input):
        avatar_file = f"{user_input}.jpg"

    avatar_path = AVATAR_DIR / avatar_file
    if not avatar_path.exists():
        yield f"头像 {user_input} 不存在，请使用 #模拟人生查看头像馆 查看可用的头像。"
        return

    data["avatar"] = avatar_file
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "set_avatar")
    yield f"你的头像已更新为：{avatar_file}"


def re_search_suffix(name: str) -> bool:
    import re

    return bool(re.search(r"\.(jpg|jpeg|png|webp)$", name, re.IGNORECASE))


@cmd(r"^#模拟人生修改签名.*$", name="change_signature", priority=2)
async def change_signature(self, event):
    """修改个性签名（首次免费，之后 300 元）"""
    require_cd(event, "mnrs", "set")
    data = await require_player(event)
    new_signature = arg_after(event, "#模拟人生修改签名")
    if not new_signature:
        yield "请输入要设置的签名，例如：#模拟人生修改签名 我是一名快乐的玩家"
        return
    if len(new_signature) > 30:
        yield "签名长度不能超过30个字符"
        return
    if any(word in new_signature for word in SENSITIVE_WORDS):
        yield "签名包含敏感词，请修改后重试"
        return

    is_first_change = data.get("signature") == "我是一名玩家"
    if not is_first_change and int(data.get("money", 0)) < 300:
        yield "你的金钱不足，修改签名需要300元"
        return
    if not is_first_change:
        data["money"] = int(data.get("money", 0)) - 300

    data["signature"] = new_signature
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "set")

    if is_first_change:
        yield f"你的签名已更新为：{new_signature}"
    else:
        yield f"你的签名已更新为：{new_signature}，扣除300元"


@cmd(r"^#查看体力药水$", name="view_stamina_potions", priority=2)
async def view_stamina_potions(self, event):
    """查看体力药水商店"""
    require_cd(event, "mnrs", "view")
    set_cd(sender_id(event), "mnrs", "view")
    lines = ["【体力药水商店】", "------------------------"]
    for potion in STAMINA_POTIONS:
        lines.append(
            f"{potion['name']}：{potion['price']}元，恢复{potion['recovery']}点体力"
        )
    lines += [
        "------------------------",
        "使用指令：#购买体力药水 [药水名称]",
        "例如：#购买体力药水 小型体力药水",
    ]
    yield "\n".join(lines)


@cmd(r"^#购买体力药水.*$", name="buy_stamina_potion", priority=9)
async def buy_stamina_potion(self, event):
    """购买体力药水"""
    require_cd(event, "mnrs", "buy")
    data = await require_player(event)
    potion_name = arg_after(event, "#购买体力药水")
    if not potion_name:
        yield "请指定要购买的体力药水名称，例如：#购买体力药水 小型体力药水"
        return
    potion = next((p for p in STAMINA_POTIONS if p["name"] == potion_name), None)
    if potion is None:
        yield "未找到该药水，请使用#查看体力药水命令查看可用的药水列表"
        return
    if int(data.get("money", 0)) < potion["price"]:
        yield f"你的金钱不足，购买{potion['name']}需要{potion['price']}元"
        return
    if backpack_is_full(data):
        yield "你的背包已满，无法购买更多物品"
        return
    data["money"] = int(data.get("money", 0)) - potion["price"]
    data.setdefault("backpack", []).append(
        {
            "type": "stamina_potion",
            "id": potion["id"],
            "name": potion["name"],
            "recovery": potion["recovery"],
        },
    )
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "buy")
    yield (
        f"你成功购买了{potion['name']}，花费{potion['price']}元。剩余金钱：{data['money']}元"
    )


@cmd(r"^#食用体力药水.*$", name="use_stamina_potion", priority=2)
async def use_stamina_potion(self, event):
    """食用体力药水恢复体力"""
    require_cd(event, "mnrs", "use")
    data = await require_player(event)
    potion_name = arg_after(event, "#食用体力药水")
    if not potion_name:
        yield "请指定要使用的体力药水名称，例如：#食用体力药水 小型体力药水"
        return
    potion = find_backpack_item(data, "stamina_potion", potion_name)
    if potion is None:
        yield f"你的背包中没有{potion_name}"
        return
    old_stamina = int(data.get("stamina", 0))
    data["stamina"] = min(100, old_stamina + int(potion.get("recovery", 0)))
    actual_recovery = data["stamina"] - old_stamina
    data["backpack"].remove(potion)
    await save(sender_id(event), data)
    set_cd(sender_id(event), "mnrs", "use")
    yield f"你使用了{potion['name']}，恢复了{actual_recovery}点体力。当前体力：{data['stamina']}/100"
