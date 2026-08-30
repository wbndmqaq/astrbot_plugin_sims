"""厨师专属烹饪料理、食谱研发与厨具加成。"""

from __future__ import annotations

from .. import gamedata


def get_recipes() -> list[dict]:
    data = gamedata.load_data("recipes.json")
    if isinstance(data, dict):
        return data.get("recipes") or []
    return []


def get_ingredients() -> list[dict]:
    data = gamedata.load_data("ingredients.json")
    if isinstance(data, dict):
        return data.get("ingredients") or []
    return []


def get_kitchenware() -> list[dict]:
    data = gamedata.load_data("kitchenware.json")
    if isinstance(data, dict):
        return data.get("kitchenware") or []
    return []
