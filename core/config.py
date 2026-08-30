"""统一配置管理器：完全集成 AstrBot _conf_schema.json 与运行时热重载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# 全局内存配置字典引用
_CURRENT_CONFIG: dict[str, Any] = {}
_FALLBACK_CACHE: dict[str, Any] = {}


def _load_fallback_yaml(filename: str) -> dict[str, Any]:
    if filename in _FALLBACK_CACHE:
        return _FALLBACK_CACHE[filename]
    path = Path(__file__).resolve().parent.parent / "resources" / "config" / filename
    if not path.exists():
        sims_defset = Path(__file__).resolve().parent.parent.parent / "sims-plugin" / "defSet" / filename
        if sims_defset.exists():
            path = sims_defset
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    _FALLBACK_CACHE[filename] = data
                    return data
        except Exception:
            pass
    return {}


def set_config(cfg: dict[str, Any] | None) -> None:
    """由 main.py Star 初始化或配置更新时注入。"""
    global _CURRENT_CONFIG
    _CURRENT_CONFIG = dict(cfg or {})


def get_config() -> dict[str, Any]:
    """获取完整配置字典。"""
    return _CURRENT_CONFIG


def get(key: str, default: Any = None) -> Any:
    """获取单个配置项（支持点分路径如 'cooldown.career_work' 或 'lottery.pools'）。"""
    if not key:
        return default
    parts = key.split(".")
    curr: Any = _CURRENT_CONFIG
    found = True
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            found = False
            break
    if found and curr is not None:
        return curr

    # Fallback to YAML definitions in resources/config/*.yaml or defSet/*.yaml
    top = parts[0]
    yaml_data = _load_fallback_yaml(f"{top}.yaml")
    if yaml_data:
        fallback_curr: Any = yaml_data
        fallback_found = True
        for p in parts[1:]:
            if isinstance(fallback_curr, dict) and p in fallback_curr:
                fallback_curr = fallback_curr[p]
            else:
                fallback_found = False
                break
        if fallback_found and fallback_curr is not None:
            return fallback_curr

    return default


def scale_pct() -> float:
    """渲染图片缩放比 (50%~250%)。"""
    raw = get("render_scale", 100)
    try:
        pct = float(raw) / 100.0
    except (TypeError, ValueError):
        pct = 1.0
    return min(2.5, max(0.5, pct))


def reply_mode() -> str:
    """回复模式：'auto' | 'text' | 'image'。"""
    return str(get("reply_mode", "auto"))

