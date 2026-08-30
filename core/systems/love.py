"""恋爱、约会、结婚与伴侣系统。"""

from __future__ import annotations

from .. import gamedata


def get_npc_characters() -> list[dict]:
    data = gamedata.load_data("npcCharacters.json")
    if isinstance(data, dict):
        return data.get("npcs") or []
    return []


def get_dating_places() -> list[dict]:
    data = gamedata.load_data("datingShop.json")
    if isinstance(data, dict):
        return data.get("places") or []
    return []


def get_wedding_packages() -> dict[str, dict]:
    data = gamedata.load_data("marriageSystem.json")
    if isinstance(data, dict):
        return data.get("packages") or {}
    return {
        "basic": {"name": "简单婚礼", "cost": 5000, "affectionBonus": 50},
        "standard": {"name": "标准婚礼", "cost": 20000, "affectionBonus": 150},
        "luxury": {"name": "豪华婚礼", "cost": 100000, "affectionBonus": 500},
    }
