"""静态游戏数据与文案管理。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PLUGIN_ROOT / "resources" / "data"
TEXTS_DIR = PLUGIN_ROOT / "resources" / "texts"

_cache: dict[str, Any] = {}


def load_data(rel_path: str) -> Any:
    """加载 resources/data/ 下的 JSON 静态数据。"""
    key = rel_path.replace("\\", "/")
    if key in _cache:
        return _cache[key]
    path = DATA_DIR / key
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = None
    _cache[key] = data
    return data


def save_data(rel_path: str, data: Any) -> bool:
    """持久化保存静态数据回 resources/data/。"""
    path = DATA_DIR / rel_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _cache[rel_path.replace("\\", "/")] = data
        return True
    except Exception:
        return False


def load_text(name: str) -> Any:
    """加载 resources/texts/ 下的文本 JSON 配置。"""
    path = TEXTS_DIR / f"{name}.json"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 兼容历史别名
_load = load_data
save_json = save_data
def get_all_items() -> dict[str, dict]:
    items = load_data("core/items.json")
    if isinstance(items, dict):
        return items.get("items") or {}
    return {}


def get_item(item_id: str) -> dict | None:
    item = get_all_items().get(item_id)
    return item if isinstance(item, dict) else None


def search_items(keyword: str) -> list[dict]:
    return [
        item
        for item in get_all_items().values()
        if keyword in str(item.get("name", ""))
        or keyword in str(item.get("description", ""))
    ]


# -------------------------------------------------------------- careers --
def get_all_careers() -> dict[str, dict]:
    careers = load_data("core/careers.json")
    if isinstance(careers, dict):
        return careers.get("careers") or {}
    return {}


def get_career(career_id: str) -> dict | None:
    career = get_all_careers().get(career_id)
    return career if isinstance(career, dict) else None


# ---------------------------------------------------------------- shops --
def get_shops() -> dict:
    shops = load_data("core/shops.json")
    return shops if isinstance(shops, dict) else {}


def save_shops(data: dict) -> bool:
    return save_data("core/shops.json", data)
