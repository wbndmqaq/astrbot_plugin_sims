"""电影院经营体系：影厅升级、排片放映与票房收益结算。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..cron import register_tick
from ..db import load_all_users, save_user


async def update_cinema_data() -> None:
    for user_id, user_data in (await load_all_users()).items():
        cinema = user_data.get("cinema")
        if not cinema:
            continue
        daily_revenue = 0
        now = datetime.now()
        for theater in cinema.get("theaters") or []:
            for schedule in theater.get("schedule") or []:
                try:
                    hour, minute = schedule["time"].split(":")
                    start = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
                    if abs((now - start).total_seconds()) <= 1800:
                        revenue = int(schedule.get("price", 50) * theater.get("capacity", 50) * (cinema.get("reputation", 50) / 100))
                        daily_revenue += revenue
                except Exception:
                    continue
        cinema["dailyRevenue"] = cinema.get("dailyRevenue", 0) + daily_revenue
        cinema["totalRevenue"] = cinema.get("totalRevenue", 0) + daily_revenue
        user_data["money"] = int(user_data.get("money", 0)) + daily_revenue
        await save_user(user_id, user_data)


async def _cinema_tick(context: Any) -> None:
    await update_cinema_data()


register_tick(_cinema_tick)
