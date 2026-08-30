"""Handler 基础设施：注册装饰器 @cmd 与公共守卫。"""

from __future__ import annotations

from typing import Any, Callable

from ..core.context import CommandError, cd_remaining, sender_id
from ..core.db import check_user, save_user

COMMAND_REGISTRY: list[dict[str, Any]] = []


def cmd(
    pattern: str,
    *,
    name: str = "",
    priority: int = 0,
    desc: str = "",
) -> Callable:
    """声明式注册 AstrBot 指令处理器。"""
    def decorator(fn: Callable) -> Callable:
        fn_name = name or fn.__name__
        COMMAND_REGISTRY.append({
            "name": fn_name,
            "func": fn,
            "pattern": pattern,
            "priority": priority,
            "desc": desc or (fn.__doc__ or "").strip(),
        })
        return fn

    return decorator


def get_commands() -> list[dict[str, Any]]:
    return COMMAND_REGISTRY


# ----------------------------------------------------------- guards --
async def require_player(event: Any) -> dict[str, Any]:
    """确保玩家已创建角色档案。"""
    user_id = sender_id(event)
    user_data = await check_user(user_id)
    if not user_data:
        raise CommandError("你还没有模拟人生角色！发送 #开始模拟人生 开启你的旅途。")
    return user_data


def require_cd(event: Any, category: str, action: str) -> None:
    """检查指令冷却。"""
    user_id = sender_id(event)
    rem = cd_remaining(user_id, category, action)
    if rem > 0:
        raise CommandError(f"操作太快啦，请等待 {rem} 秒后再试～")


# 兼容历史别名
save = save_user
