"""二次元农场系统：土地开荒、种植打理、作物生长与季节演变。"""

from __future__ import annotations

import random
import time
from typing import Any

from .. import gamedata
from ..cron import register_tick
from ..db import db

FARM_KV = "farm_state"


async def load_all_farms() -> dict[str, dict]:
    data = await db.read_kv(FARM_KV, {})
    return data if isinstance(data, dict) else {}


async def save_all_farms(data: dict) -> None:
    await db.write_kv(FARM_KV, data)


def get_seeds() -> list[dict]:
    return (gamedata.load_data("farm/seeds.json") or {}).get("seeds") or []


def get_tools() -> list[dict]:
    return (gamedata.load_data("farm/tools.json") or {}).get("tools") or []


def get_land_upgrades() -> list[dict]:
    return (gamedata.load_data("farm/land_upgrades.json") or {}).get("landUpgrades") or []


def get_events() -> list[dict]:
    return (gamedata.load_data("farm/events.json") or {}).get("events") or []


def get_seasons() -> list[dict]:
    return (gamedata.load_data("farm/seasons.json") or {}).get("seasons") or []


def get_current_season() -> dict:
    seasons = get_seasons()
    if not seasons:
        return {"name": "春季", "icon": "🌸", "growthSpeed": 1.0, "yieldRate": 1.0}
    day_of_year = time.localtime().tm_yday
    idx = (day_of_year // 90) % len(seasons)
    return seasons[idx]


async def update_farms() -> None:
    """每小时农田作物生长与健康衰减结算。"""
    farms = await load_all_farms()
    if not farms:
        return
    now = time.time() * 1000
    season = get_current_season()
    events = get_events()
    dirty = False

    for _fid, farm in farms.items():
        plots = farm.get("plots") or []
        for plot in plots:
            crop = plot.get("crop")
            if not crop:
                continue
            # 生长进度推进
            growth_speed = season.get("growthSpeed", 1.0)
            health = crop.get("health", 100)
            if health < 50:
                growth_speed *= 0.5
            growth_days = crop.get("growthDays", 3)
            progress = min(100, crop.get("progress", 0) + (100 / (growth_days * 24)) * growth_speed)
            crop["progress"] = progress
            if progress >= 100:
                crop["stage"] = "mature"
            elif progress >= 50:
                crop["stage"] = "growing"
            else:
                crop["stage"] = "seed"

            # 水分与养分自然衰减
            plot["waterLevel"] = max(0, plot.get("waterLevel", 100) - 4)
            plot["fertilizerLevel"] = max(0, plot.get("fertilizerLevel", 100) - 2)
            if plot["waterLevel"] < 20:
                crop["health"] = max(0, health - 5)

            # 随机农场事件
            if events and random.random() < 0.05:
                ev = random.choice(events)
                farm.setdefault("logs", []).append({
                    "time": now,
                    "event": ev.get("name"),
                    "desc": ev.get("desc", ""),
                })
            dirty = True

    if dirty:
        await save_all_farms(farms)


async def _farm_tick(context: Any) -> None:
    await update_farms()


register_tick(_farm_tick)
