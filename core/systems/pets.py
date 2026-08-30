"""宠物捕捉、喂养、互动与放生。"""

from __future__ import annotations

from .. import gamedata


def get_pet_pool() -> list[dict]:
    data = gamedata.load_data("petPool.json")
    if isinstance(data, dict):
        return data.get("pets") or []
    return []
