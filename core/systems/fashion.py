"""时装商城、部位穿戴与属性加成。"""

from __future__ import annotations

from .. import gamedata


def get_fashion_data() -> dict[str, list[dict]]:
    data = gamedata.load_data("fashion.json")
    if isinstance(data, dict):
        return data.get("fashion") or {}
    return {}
