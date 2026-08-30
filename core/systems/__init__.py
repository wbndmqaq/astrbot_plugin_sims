"""核心业务系统统一导出。"""

from __future__ import annotations

# 导入所有业务系统以触发钩子与初始化注册
from . import (
    achievement,
    career,
    chef,
    cinema,
    farm,
    fashion,
    fishing,
    lottery,
    love,
    netbar,
    pets,
    player,
    stocks,
    tavern,
    world,
)
from . import (
    property as property_sys,
)

__all__ = [
    "achievement",
    "career",
    "chef",
    "cinema",
    "farm",
    "fashion",
    "fishing",
    "lottery",
    "love",
    "netbar",
    "pets",
    "player",
    "property_sys",
    "stocks",
    "tavern",
    "world",
]
