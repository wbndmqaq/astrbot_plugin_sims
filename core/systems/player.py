"""主角色系统业务逻辑。"""

from __future__ import annotations

import random
import string
from typing import Any

SENSITIVE_WORDS = ["狗", "傻", "笨", "死", "操", "日", "逼", "草", "妈", "爸", "爷", "孙"]

STAMINA_POTIONS = [
    {"id": "potion_001", "name": "小型体力药水", "stamina": 30, "price": 100, "recovery": 30, "desc": "恢复30点体力"},
    {"id": "potion_002", "name": "中型体力药水", "stamina": 60, "price": 180, "recovery": 60, "desc": "恢复60点体力"},
    {"id": "potion_003", "name": "大型体力药水", "stamina": 100, "price": 280, "recovery": 100, "desc": "恢复100点体力"},
    {"id": "potion_004", "name": "超级体力药水", "stamina": 200, "price": 500, "recovery": 200, "desc": "恢复200点体力"},
]


def new_player_data(name: str | None = None) -> dict[str, Any]:
    if not name:
        name = "玩家" + "".join(random.choices(string.digits, k=4))
    return {
        "name": name,
        "signature": "这个人很懒，什么都没写~",
        "gender": random.choice(["男", "女"]),
        "avatar": "1.jpg",
        "level": 1,
        "money": 1000,
        "stamina": 100,
        "happiness": 100,
        "health": 100,
        "life": 100,
        "thirst": 100,
        "hunger": 100,
        "charm": 10,
        "mood": 100,
        "job": "无",
        "disease": "无",
        "partnerAffection": 0,
        "relationshipStatus": "单身",
        "consecutiveSignIn": 0,
        "lastSignInDate": "",
        "backpack": [],
        "inventory": {},
        "created_at": int(random.random() * 1000),
    }


def find_backpack_item(data: dict, item_type: str, name: str) -> dict | None:
    for it in data.get("backpack", []):
        if it.get("type") == item_type and it.get("name") == name:
            return it
    return None


def backpack_is_full(data: dict, limit: int = 50) -> bool:
    return len(data.get("backpack", [])) >= limit
