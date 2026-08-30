"""后台定时调度器：每小时 Tick、日常刷新与系统状态维护。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Callable

from .db import load_all_users, save_user

_tick_hooks: list[Callable[[Any], Any]] = []


def register_tick(hook: Callable[[Any], Any]) -> None:
    """注册每小时定时 Tick 钩子。"""
    if hook not in _tick_hooks:
        _tick_hooks.append(hook)


async def run_hourly_tick(context: Any = None) -> dict[str, Any]:
    """执行每小时业务结算：网吧、影院、农场、股市波动、随机事件等。"""
    now = datetime.now()
    now_ts = int(time.time() * 1000)

    users = await load_all_users()
    for user_id, user_data in users.items():
        dirty = False

        # 1. 网吧每小时营业收益
        netbar = user_data.get("netbar")
        if netbar:
            from .systems.netbar import calculate_hourly_income
            income = calculate_hourly_income(netbar)
            if income > 0:
                user_data["money"] = int(user_data.get("money", 0)) + income
                netbar["totalRevenue"] = int(netbar.get("totalRevenue", 0)) + income
                netbar["dailyRevenue"] = int(netbar.get("dailyRevenue", 0)) + income
                dirty = True

        # 2. 房产租金收益结算
        properties = user_data.get("properties") or []
        for prop in properties:
            if prop.get("isRented"):
                rent = int(prop.get("rentPrice", 0) or 0)
                if rent > 0:
                    user_data["money"] = int(user_data.get("money", 0)) + rent
                    dirty = True

        # 3. 跨日重置 (每日 0 点)
        today_str = now.strftime("%Y-%m-%d")
        if user_data.get("_last_daily_reset") != today_str and now.hour == 0:
            user_data["_last_daily_reset"] = today_str
            # 重置今日工作次数
            if user_data.get("career"):
                user_data["career"]["dailyWork"] = 0
                dirty = True
            # 重置店铺日营收统计
            if netbar:
                netbar["dailyRevenue"] = 0
                dirty = True
            if user_data.get("cinema"):
                user_data["cinema"]["dailyRevenue"] = 0
                dirty = True
            if user_data.get("tavern"):
                stats = user_data["tavern"].setdefault("stats", {})
                stats["dailyRevenue"] = 0
                stats["dailyCustomers"] = 0
                dirty = True

        if dirty:
            await save_user(user_id, user_data)

    # 4. 执行各系统注册的全局 Tick 钩子
    for hook in list(_tick_hooks):
        try:
            res = hook(context)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

    return {"status": "ok", "time": now_ts}
