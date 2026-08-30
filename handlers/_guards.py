"""Shared handler guards - async version.

Full async support for user verification, archive loading, and ban checks.
"""

from __future__ import annotations

from typing import Any

from ..core.context import CommandError, cd_remaining, sender_id
from ..core.db import check_banned, get_player_ref

DEFAULT_PLAYER = {
    "name": None,
    "money": 1000,
    "happiness": 100,
    "life": 100,
    "hunger": 100,
    "thirst": 100,
    "charm": 50,
    "mood": 100,
    "signature": "我是一名玩家",
    "gender": "未知",
    "disease": None,
    "status": "健康",
    "job": None,
    "level": 1,
    "stamina": 100,
    "partnerAffection": 0,
    "relationshipStatus": "单身",
    "time": 0,
    "weather": "晴天",
    "temperature": 25,
    "backpack": [],
    "backpackCapacity": 100,
    "location": "家",
    "familyHappiness": 100,
    "overdueTasks": 0,
    "avatar": "default.jpg",
    "lastSignInDate": None,
    "dailySignIn": False,
    "consecutiveSignIn": 0,
    "bank": {
        "balance": 0,
        "savingsLimit": 10000,
        "deposits": [],
    },
    "inventory": {},
    "equipment": {},
}


def new_player_data(name: str | None = None) -> dict[str, Any]:
    import random
    import string

    if name is None:
        characters = string.ascii_letters + string.digits + "涩批地球"
        name = "玩家" + "".join(random.choice(characters) for _ in range(7))
    data = dict(DEFAULT_PLAYER)
    data["name"] = name
    data["backpack"] = []
    data["bank"] = {
        "balance": 0,
        "savingsLimit": 10000,
        "deposits": [],
    }
    data["inventory"] = {}
    data["equipment"] = {}
    return data


async def ensure_not_banned(user_id: str) -> None:
    until = await check_banned(user_id)
    if until:
        from datetime import datetime

        readable = datetime.fromtimestamp(until / 1000).strftime("%Y-%m-%d %H:%M:%S")
        raise CommandError(
            f"你已被封禁，无法进行操作。（解封时间：{readable}）",
        )


def require_cd(event: Any, category: str, cd_type: str) -> None:
    remaining = cd_remaining(sender_id(event), category, cd_type)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试～")


async def require_player(event: Any, *, repair: bool = True) -> dict[str, Any]:
    """异步加载调用者存档；不存在时抛出 CommandError."""
    user_id = sender_id(event)
    await ensure_not_banned(user_id)
    data = await get_player_ref(user_id)
    if data is None:
        raise CommandError("未找到您的游戏数据，请使用 #开始模拟人生 创建角色")
    if repair:
        changed = False
        for key, value in DEFAULT_PLAYER.items():
            if key not in data:
                data[key] = value
                changed = True
        bank = data.get("bank")
        if not isinstance(bank, dict):
            data["bank"] = dict(DEFAULT_PLAYER["bank"])
            changed = True
        if changed:
            from ..core.db import save_user

            await save_user(user_id, data)
    return data


async def save(user_id: str, data: dict[str, Any]) -> None:
    from ..core.db import save_user

    await save_user(user_id, data)


# ---------------------------------------------------------------- items --
def find_backpack_item(data: dict, item_type: str, name: str) -> dict | None:
    for item in data.get("backpack", []):
        if item.get("type") == item_type and item.get("name") == name:
            return item
    return None


def backpack_is_full(data: dict) -> bool:
    return len(data.get("backpack", [])) >= int(data.get("backpackCapacity", 100))


STAMINA_POTIONS = [
    {"id": "potion_small", "name": "小型体力药水", "price": 50, "recovery": 20},
    {"id": "potion_medium", "name": "中型体力药水", "price": 100, "recovery": 40},
    {"id": "potion_large", "name": "大型体力药水", "price": 200, "recovery": 80},
]

SENSITIVE_WORDS = [
    "裸露",
    "fuck",
    "傻逼",
    "操你",
    "人机",
    "cnm",
    "草泥马",
    "nmsl",
    "你妈",
    "尼玛",
    "nmb",
]
