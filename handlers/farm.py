"""农场系统 - port of ``apps/farm.js`` (FarmSystem).

14 commands covering farm creation, land upgrades, seed/tool shop, planting,
watering, fertilizing, harvesting, logs, guide and seasons, plus the hourly
``updateFarms`` cron (growth/health decay/random events) registered through
:mod:`astrbot_plugin_sims.sims.cron`.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import get_store
from ..core.renderer import renderer
from .base import cmd

FARM_KV = "farm_data"


# ------------------------------------------------------------- data load --
async def _load_farm_data() -> dict[str, Any]:
    data = await get_store().read_kv(FARM_KV, {})
    return data if isinstance(data, dict) else {}


async def _save_farm_data(data: dict[str, Any]) -> None:
    await get_store().write_kv(FARM_KV, data)


def _seeds() -> list[dict]:
    return (game_data._load("farm/seeds.json") or {}).get("seeds") or []


def _tools() -> list[dict]:
    return (game_data._load("farm/tools.json") or {}).get("tools") or []


def _land_upgrades() -> list[dict]:
    return (game_data._load("farm/land_upgrades.json") or {}).get("landUpgrades") or []


def _events() -> list[dict]:
    return (game_data._load("farm/events.json") or {}).get("events") or []


def _seasons() -> list[dict]:
    return (game_data._load("farm/seasons.json") or {}).get("seasons") or []


def get_current_season() -> dict:
    month = datetime.now().month
    seasons = _seasons()
    for season in seasons:
        if month in (season.get("months") or []):
            return season
    return next(
        (s for s in seasons if s.get("name") == "春季"), seasons[0] if seasons else {}
    )


async def _require_farm(user_id: str) -> dict[str, Any]:
    farm = (await _load_farm_data()).get(user_id)
    if farm is None:
        raise CommandError("你还没有农场！使用 #创建农场 来创建一个。")
    return farm


def _require_cd(event, category: str, action: str) -> None:
    remaining = cd_remaining(sender_id(event), category, action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")


async def _require_player(event) -> dict:
    from . import base as _guards

    return await _guards.require_player(event)
    from . import base as _guards


def _new_plot() -> dict[str, Any]:
    return {
        "crop": None,
        "plantedAt": None,
        "water": 0,
        "fertility": 0,
        "health": 100,
        "growthStage": 0,
        "harvestReady": False,
    }


def _log(farm: dict, action: str, description: str) -> None:
    farm.setdefault("log", []).append(
        {
            "date": datetime.now().isoformat(),
            "action": action,
            "description": description,
        },
    )


def _css_file() -> str:
    from ..core.renderer import BASE_HREF_DIR

    return BASE_HREF_DIR.as_uri() + "/"


# ------------------------------------------------------------ hourly tick --
async def update_farms() -> None:
    farm_data = await _load_farm_data()
    current_season = get_current_season()
    now = datetime.now()
    changed = False
    for farm in farm_data.values():
        farm["lastUpdate"] = now.isoformat()
        land = farm.get("land") or {}
        retention = land.get("waterRetention", 1) or 1
        fertility_bonus = land.get("fertilityBonus", 1) or 1
        for i, plot in enumerate(land.get("plots") or []):
            if not plot.get("crop"):
                continue
            crop_info = next(
                (s for s in _seeds() if s.get("name") == plot["crop"]), None
            )
            if crop_info is None:
                continue
            is_right_season = current_season.get("name") in (
                crop_info.get("season") or []
            )
            seasonal_factor = 1.2 if is_right_season else 0.8

            plot["water"] = max(0, plot["water"] - (5 / retention))
            plot["fertility"] = max(0, plot["fertility"] - (2 / fertility_bonus))

            planted = datetime.fromisoformat(plot["plantedAt"])
            days_passed = (now - planted).days
            water_effect = 1 if plot["water"] >= 50 else plot["water"] / 50
            fertility_effect = 1 if plot["fertility"] >= 30 else plot["fertility"] / 30
            health_change = water_effect * fertility_effect * seasonal_factor * 2 - 1
            plot["health"] = max(0, min(100, plot["health"] + health_change))

            growth_days = crop_info.get("growthDays", 5)
            if days_passed >= growth_days and plot["health"] > 30:
                plot["harvestReady"] = True
                plot["growthStage"] = 3
            elif days_passed >= growth_days * 0.7:
                plot["growthStage"] = 2
            elif days_passed >= growth_days * 0.3:
                plot["growthStage"] = 1

            if plot["health"] <= 10 and random.random() < 0.1:
                _log(
                    farm,
                    "作物死亡",
                    f"第{i + 1}号地块的{plot['crop']}因缺乏照顾而死亡",
                )
                empty = _new_plot()
                plot.update(empty)
        _trigger_random_event(farm)
        active = []
        for event in farm.get("activeEvents") or []:
            event["duration"] -= 1
            if event["duration"] > 0:
                active.append(event)
            else:
                _log(farm, "事件结束", f"{event['name']}的影响已结束")
        farm["activeEvents"] = active
        changed = True
    if changed:
        await _save_farm_data(farm_data)


def _trigger_random_event(farm: dict) -> None:
    if random.random() >= 0.2:
        return
    events = _events()
    total_weight = sum(e.get("probability", 0) for e in events)
    pick = random.random() * total_weight
    selected = None
    for event in events:
        pick -= event.get("probability", 0)
        if pick <= 0:
            selected = event
            break
    if selected is None:
        return
    if any(e.get("id") == selected.get("id") for e in farm.get("activeEvents") or []):
        return
    farm.setdefault("activeEvents", []).append(
        {
            "id": selected.get("id"),
            "name": selected.get("name"),
            "type": selected.get("type"),
            "effect": selected.get("effect"),
            "description": selected.get("description"),
            "duration": selected.get("duration"),
            "remedy": selected.get("remedy"),
        },
    )
    _log(farm, "事件发生", selected.get("description", ""))
    _apply_event_effects(farm, selected)


def _apply_event_effects(farm: dict, event: dict) -> None:
    effect = event.get("effect") or {}
    event_type = event.get("type")
    for plot in farm.get("land", {}).get("plots", []):
        if event_type == "weather":
            if plot.get("crop"):
                if effect.get("water"):
                    plot["water"] = max(0, min(100, plot["water"] + effect["water"]))
                if effect.get("growth"):
                    planted = datetime.fromisoformat(plot["plantedAt"])
                    planted -= timedelta(days=int(effect["growth"]))
                    plot["plantedAt"] = planted.isoformat()
        elif event_type in {"pest", "disaster"}:
            if plot.get("crop"):
                if effect.get("health"):
                    plot["health"] = max(0, min(100, plot["health"] + effect["health"]))
                if effect.get("yield"):
                    plot["yieldModifier"] = (
                        plot.get("yieldModifier", 0) + effect["yield"]
                    )
        elif event_type == "soil":
            if effect.get("fertility"):
                plot["fertility"] = max(
                    0,
                    min(100, plot["fertility"] + effect["fertility"]),
                )
    if event_type == "blessing":
        if effect.get("experience"):
            farm["experience"] = farm.get("experience", 0) + effect["experience"]
            _check_level_up(farm)
        if effect.get("quality"):
            farm["qualityModifier"] = farm.get("qualityModifier", 0) + effect["quality"]


def _check_level_up(farm: dict) -> None:
    next_level_exp = farm.get("level", 1) * 100
    if farm.get("experience", 0) >= next_level_exp:
        farm["level"] = farm.get("level", 1) + 1
        farm["experience"] -= next_level_exp
        _log(farm, "农场升级", f"农场等级提升到{farm['level']}")


register_tick(lambda context: _run_tick())


async def _run_tick() -> None:
    await update_farms()


# ------------------------------------------------------------- commands --
@cmd(r"^#创建农场$", name="farm_create", priority=7)
async def farm_create(self, event):
    """创建你的农场（500金币）"""
    _require_cd(event, "farm", "create")
    user_id = sender_id(event)
    player = await _require_player(event)
    farm_data = await _load_farm_data()
    if user_id in farm_data:
        yield "你已经拥有一个农场了！使用 #我的农场 查看。"
        return
    if int(player.get("money", 0)) < 500:
        yield "创建农场需要500金币，你的金币不足！"
        return
    player["money"] = int(player.get("money", 0)) - 500
    from . import base as _guards

    await _guards.save(user_id, player)

    upgrades = _land_upgrades()
    initial = next((l for l in upgrades if l.get("level") == 1), None) or {
        "level": 1,
        "name": "初级农田",
        "size": 4,
        "waterRetention": 1,
        "fertilityBonus": 1,
    }
    farm = {
        "name": f"{player.get('name')}的农场",
        "level": 1,
        "experience": 0,
        "createdAt": datetime.now().isoformat(),
        "lastUpdate": datetime.now().isoformat(),
        "land": {
            "level": initial["level"],
            "name": initial["name"],
            "size": initial["size"],
            "plots": [_new_plot() for _ in range(initial["size"])],
            "waterRetention": initial["waterRetention"],
            "fertilityBonus": initial["fertilityBonus"],
        },
        "inventory": {
            "seeds": [],
            "crops": [],
            "tools": [
                {"id": 1, "name": "基础锄头", "durability": 50, "efficiency": 1},
                {"id": 4, "name": "小水壶", "durability": 40, "efficiency": 1},
            ],
        },
        "statistics": {
            "totalHarvested": 0,
            "totalIncome": 0,
            "plantsGrown": 0,
            "timeSpent": 0,
        },
        "log": [
            {
                "date": datetime.now().isoformat(),
                "action": "创建",
                "description": f"{player.get('name')}创建了农场",
            },
        ],
        "activeEvents": [],
    }
    farm_data[user_id] = farm
    await _save_farm_data(farm_data)
    set_cd(user_id, "farm", "create")

    path = await renderer.render_image(
        "farm_created",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "userName": player.get("name"),
            "plots": farm["land"]["size"],
            "currentSeason": get_current_season(),
        },
    )
    yield event.image_result(path)


@cmd(r"^#我的农场$", name="farm_view", priority=7)
async def farm_view(self, event):
    """查看农场状态与作物生长"""
    _require_cd(event, "farm", "view")
    user_id = sender_id(event)
    farm = await _require_farm(user_id)
    set_cd(user_id, "farm", "view")

    level = farm.get("level", 1)
    plots_data = []
    now = datetime.now()
    for i, plot in enumerate(farm["land"].get("plots") or []):
        if plot.get("crop"):
            crop_info = next(
                (s for s in _seeds() if s.get("name") == plot["crop"]),
                None,
            )
            planted = datetime.fromisoformat(plot["plantedAt"])
            days_passed = (now - planted).days
            growth_days = max(1, crop_info.get("growthDays", 5) if crop_info else 5)
            plots_data.append(
                {
                    "index": i + 1,
                    "crop": plot["crop"],
                    "water": plot["water"],
                    "fertility": plot["fertility"],
                    "health": plot["health"],
                    "growthStage": plot["growthStage"],
                    "growthPercentage": min(
                        100,
                        math.floor(days_passed / growth_days * 100),
                    ),
                    "harvestReady": plot["harvestReady"],
                    "icon": crop_info.get("icon", "default_crop.png")
                    if crop_info
                    else "default_crop.png",
                },
            )
        else:
            plots_data.append(
                {
                    "index": i + 1,
                    "crop": None,
                    "water": 0,
                    "fertility": 0,
                    "health": 0,
                    "growthStage": 0,
                    "growthPercentage": 0,
                    "harvestReady": False,
                    "icon": "empty_plot.png",
                    "isEmpty": True,
                },
            )

    seeds_count = sum(s.get("count", 0) for s in farm["inventory"].get("seeds", []))
    crops_count = sum(c.get("count", 0) for c in farm["inventory"].get("crops", []))
    path = await renderer.render_image(
        "farm_view",
        {
            "cssFile": _css_file(),
            "farm": farm,
            "currentSeason": get_current_season(),
            "level": level,
            "nextLevelExp": level * 100,
            "currentExp": farm.get("experience", 0),
            "plotsData": plots_data,
            "seedsCount": seeds_count,
            "cropsCount": crops_count,
            "toolsCount": len(farm["inventory"].get("tools", [])),
        },
    )
    yield event.image_result(path)


async def _upgrade_land(event, *, check_level: bool, category: str):
    _require_cd(event, "farm", category)
    user_id = sender_id(event)
    player = await _require_player(event)
    farm = await _require_farm(user_id)
    _require_cd(event, "farm", category)
    user_id = sender_id(event)
    player = await _require_player(event)
    farm = await _require_farm(user_id)
    upgrades = _land_upgrades()
    current_level = farm["land"]["level"]
    if current_level >= len(upgrades):
        return "你的农田已经是最高等级了！"
    next_land = next((l for l in upgrades if l.get("level") == current_level + 1), None)
    if next_land is None:
        return "你的农田已经是最高等级了！"
    if check_level and farm.get("level", 1) < next_land.get("requiredLevel", 0):
        return (
            f"升级到{next_land['name']}需要农场等级达到{next_land['requiredLevel']}级，"
            "你的农场等级不足！"
        )
    if int(player.get("money", 0)) < next_land["price"]:
        return f"升级农田需要{next_land['price']}金币，你的金币不足！"

    player["money"] = int(player.get("money", 0)) - next_land["price"]
    from . import base as _guards

    await _guards.save(user_id, player)

    plots = farm["land"]["plots"]
    for _ in range(next_land["size"] - len(plots)):
        plots.append(_new_plot())
    farm["land"].update(
        {
            "level": next_land["level"],
            "name": next_land["name"],
            "size": next_land["size"],
            "waterRetention": next_land["waterRetention"],
            "fertilityBonus": next_land["fertilityBonus"],
        },
    )
    _log(farm, "升级农田", f"农田升级到{next_land['name']}")
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", category)
    return (
        f"恭喜你成功购买了更大的农田！农田已升级为 {next_land['name']}，"
        f"现在共有 {next_land['size']} 块地块。\n\n【农场攻略】\n"
        "升级农田可以获得更多地块和更好的土壤效果。更高级的土地有更好的保水性和肥力，"
        "让你的作物生长更快、产量更高。下一步可以使用 #农场商店 购买种子和工具。"
    )


@cmd(r"^#购买农田$", name="farm_buy_land", priority=7)
async def farm_buy_land(self, event):
    """购买更大的农田"""
    yield await _upgrade_land(event, check_level=False, category="buy")


@cmd(r"^#升级农田$", name="farm_upgrade_land", priority=7)
async def farm_upgrade_land(self, event):
    """升级农田等级（需农场等级达标）"""
    yield await _upgrade_land(event, check_level=True, category="upgrade")


@cmd(r"^#农场季节$", name="farm_season", priority=7)
async def farm_season(self, event):
    """查看当前季节与效果"""
    current = get_current_season()
    seasons = _seasons()
    idx = next(
        (i for i, s in enumerate(seasons) if s.get("id") == current.get("id")), 0
    )
    nxt = seasons[(idx + 1) % len(seasons)] if seasons else {}
    effects = current.get("effects") or {}
    yield (
        f"当前季节：{current.get('name')}\n\n{current.get('description', '')}\n\n"
        f"季节效果：\n- 生长速度：{effects.get('growth')}倍\n"
        f"- 水分消耗：{effects.get('water')}倍\n"
        f"- 温度：{effects.get('temperature')}\n\n"
        f"{current.get('special', '')}\n\n下一个季节将是：{nxt.get('name')}"
    )


@cmd(r"^#农场攻略$", name="farm_guide", priority=7)
async def farm_guide(self, event):
    """查看农场玩法攻略"""
    yield (
        "农场系统攻略已生成，请查看插件目录下的「模拟人生种菜攻略.md」文件获取详细指南。\n\n"
        "基本命令：\n#创建农场 - 开始你的农场之旅\n#我的农场 - 查看农场状态\n"
        "#农场商店 - 购买种子和工具\n#种植 [种子名称] [地块编号] - 种植作物\n"
        "#浇水 [地块编号] - 给作物浇水\n#收获 [地块编号] - 收获作物"
    )


ACTION_CLASS_RULES = [
    ("创建", "create"),
    ("种植", "plant"),
    ("浇水", "water"),
    ("施肥", "fertilize"),
    ("收获", "harvest"),
    ("升级", "upgrade"),
    ("事件", "event"),
]


@cmd(r"^#农场日志$", name="farm_log", priority=7)
async def farm_log(self, event):
    """查看农场最近活动记录"""
    _require_cd(event, "farm", "log")
    user_id = sender_id(event)
    farm = await _require_farm(user_id)
    set_cd(user_id, "farm", "log")

    logs = []
    for entry in farm.get("log", []):
        log_date = datetime.fromisoformat(entry["date"])
        action = entry.get("action", "")
        action_class = "default"
        for keyword, cls in ACTION_CLASS_RULES:
            if keyword in action.lower():
                action_class = cls
                break
        logs.append(
            {
                "date": log_date.strftime("%Y-%m-%d %H:%M"),
                "action": action,
                "description": entry.get("description", ""),
                "actionClass": action_class,
            },
        )
    logs.reverse()
    path = await renderer.render_image(
        "farm_log",
        {
            "cssFile": _css_file(),
            "farmName": farm.get("name"),
            "logs": logs[:20],
        },
    )
    yield event.image_result(path)


def _find_tool(farm: dict, keyword: str) -> dict | None:
    return next(
        (
            t
            for t in farm["inventory"].get("tools", [])
            if keyword in t.get("name", "") and t.get("durability", 0) > 0
        ),
        None,
    )


def _plot_index(event, prefix: str, farm: dict) -> int:
    raw = event.get_message_str()
    import re

    rest = re.sub(rf"^#{prefix}\s*", "", raw).strip()
    try:
        idx = int(rest) - 1
    except ValueError:
        idx = -1
    if idx < 0 or idx >= len(farm["land"]["plots"]):
        raise CommandError(
            f"无效的地块编号，请使用 #{prefix} [1-{len(farm['land']['plots'])}] "
            "来操作对应地块。",
        )
    return idx


@cmd(r"^#收获.*$", name="farm_harvest", priority=7)
async def farm_harvest(self, event):
    """收获成熟作物：#收获 [地块编号]"""
    _require_cd(event, "farm", "harvest")
    user_id = sender_id(event)
    farm = await _require_farm(user_id)
    plot_index = _plot_index(event, "收获", farm)
    plot = farm["land"]["plots"][plot_index]
    if not plot.get("crop"):
        yield f"第{plot_index + 1}号地块没有种植作物！"
        return
    if not plot.get("harvestReady"):
        yield f"第{plot_index + 1}号地块的{plot['crop']}还没有成熟，请耐心等待。"
        return
    scythe = _find_tool(farm, "镰刀")
    if scythe is None:
        yield "你没有可用的镰刀工具！请先从农场商店购买。"
        return
    scythe["durability"] -= 1

    crop_info = next((s for s in _seeds() if s.get("name") == plot["crop"]), None)
    health_factor = plot["health"] / 100
    quality_modifier = farm.get("qualityModifier", 0)
    yield_modifier = plot.get("yieldModifier", 0)
    harvest_amount = math.floor(
        crop_info["yield"]
        * health_factor
        * (1 + (quality_modifier + yield_modifier) / 100),
    )
    harvest_amount = max(1, harvest_amount)

    existing = next(
        (c for c in farm["inventory"]["crops"] if c["name"] == plot["crop"]),
        None,
    )
    quality = math.floor(plot["health"] / 20) + 1
    if existing:
        existing["count"] += harvest_amount
    else:
        farm["inventory"]["crops"].append(
            {
                "name": plot["crop"],
                "count": harvest_amount,
                "price": crop_info.get("sellPrice", 0),
                "quality": quality,
            },
        )

    farm["statistics"]["totalHarvested"] += harvest_amount
    farm["statistics"]["plantsGrown"] += 1
    farm["experience"] = farm.get("experience", 0) + 10
    _check_level_up(farm)
    _log(
        farm,
        "收获",
        f"收获了第{plot_index + 1}号地块的{plot['crop']} x{harvest_amount}",
    )
    crop_name = plot["crop"]
    empty = _new_plot()
    plot.update(empty)
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", "harvest")

    path = await renderer.render_image(
        "harvest_crop",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "cropName": crop_name,
            "harvestAmount": harvest_amount,
            "quality": quality,
            "plotIndex": plot_index + 1,
            "exp": 10,
            "toolDurability": scythe["durability"],
        },
    )
    yield event.image_result(path)


@cmd(r"^#施肥.*$", name="farm_fertilize", priority=7)
async def farm_fertilize(self, event):
    """给地块施肥：#施肥 [地块编号]"""
    _require_cd(event, "farm", "fertilize")
    user_id = sender_id(event)
    farm = await _require_farm(user_id)
    plot_index = _plot_index(event, "施肥", farm)
    plot = farm["land"]["plots"][plot_index]
    if not plot.get("crop"):
        yield f"第{plot_index + 1}号地块没有种植作物！"
        return
    if plot["fertility"] >= 100:
        yield f"第{plot_index + 1}号地块已经很肥沃了，不需要继续施肥。"
        return
    fertilizer = _find_tool(farm, "肥料")
    if fertilizer is None:
        yield "你没有可用的肥料！请先从农场商店购买。"
        return
    fertilizer["durability"] -= 1
    efficiency = fertilizer.get("efficiency", 1) or 1
    old_fertility = plot["fertility"]
    plot["fertility"] = min(100, plot["fertility"] + 20 * efficiency)
    if plot["fertility"] > 80 and random.random() < 0.2:
        plot["health"] = max(50, plot["health"] - 5)

    _log(
        farm,
        "施肥",
        f"对第{plot_index + 1}号地块施肥，肥力从{round(old_fertility)}%"
        f"提升到{round(plot['fertility'])}%",
    )
    farm["experience"] = farm.get("experience", 0) + 3
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", "fertilize")

    path = await renderer.render_image(
        "fertilize_crop",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "cropName": plot["crop"],
            "plotIndex": plot_index + 1,
            "oldFertility": round(old_fertility),
            "newFertility": round(plot["fertility"]),
            "toolName": fertilizer["name"],
            "toolDurability": fertilizer["durability"],
        },
    )
    yield event.image_result(path)


@cmd(r"^#浇水.*$", name="farm_water", priority=7)
async def farm_water(self, event):
    """给地块浇水：#浇水 [地块编号]"""
    _require_cd(event, "farm", "water")
    user_id = sender_id(event)
    farm = await _require_farm(user_id)
    plot_index = _plot_index(event, "浇水", farm)
    plot = farm["land"]["plots"][plot_index]
    if not plot.get("crop"):
        yield f"第{plot_index + 1}号地块没有种植作物！"
        return
    if plot["water"] >= 100:
        yield f"第{plot_index + 1}号地块已经很湿润了，不需要继续浇水。"
        return
    can = _find_tool(farm, "水壶")
    if can is None:
        yield "你没有可用的水壶！请先从农场商店购买。"
        return
    can["durability"] -= 1
    efficiency = can.get("efficiency", 1) or 1
    old_water = plot["water"]
    plot["water"] = min(100, plot["water"] + 25 * efficiency)
    if plot["water"] > 90 and random.random() < 0.2:
        plot["health"] = max(60, plot["health"] - 3)

    _log(
        farm,
        "浇水",
        f"对第{plot_index + 1}号地块浇水，水分从{round(old_water)}%"
        f"提升到{round(plot['water'])}%",
    )
    farm["experience"] = farm.get("experience", 0) + 2
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", "water")

    path = await renderer.render_image(
        "water_crop",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "cropName": plot["crop"],
            "plotIndex": plot_index + 1,
            "oldWater": round(old_water),
            "newWater": round(plot["water"]),
            "toolName": can["name"],
            "toolDurability": can["durability"],
        },
    )
    yield event.image_result(path)


@cmd(r"^#种植.*$", name="farm_plant", priority=7)
async def farm_plant(self, event):
    """播种：#种植 [种子名称] [地块编号]"""
    _require_cd(event, "farm", "plant")
    user_id = sender_id(event)
    farm = await _require_farm(user_id)
    import re

    rest = re.sub(r"^#种植\s*", "", event.get_message_str()).strip()
    parts = rest.split()
    if len(parts) < 2:
        yield "命令格式错误，正确格式：#种植 [种子名称] [地块编号]"
        return
    seed_name = parts[0]
    try:
        plot_index = int(parts[1]) - 1
    except ValueError:
        plot_index = -1
    if plot_index < 0 or plot_index >= len(farm["land"]["plots"]):
        yield f"无效的地块编号，请使用 1-{len(farm['land']['plots'])} 的数字。"
        return
    plot = farm["land"]["plots"][plot_index]
    if plot.get("crop"):
        yield f"第{plot_index + 1}号地块已经种植了{plot['crop']}，请先收获或等待作物死亡。"
        return

    seed_entry = next(
        (
            s
            for s in farm["inventory"].get("seeds", [])
            if s.get("name") == seed_name and s.get("count", 0) > 0
        ),
        None,
    )
    if seed_entry is None:
        yield f"你没有{seed_name}种子，请先从农场商店购买。"
        return
    hoe = _find_tool(farm, "锄头")
    if hoe is None:
        yield "你没有可用的锄头工具！请先从农场商店购买。"
        return
    hoe["durability"] -= 1

    seed_info = next((s for s in _seeds() if s.get("name") == seed_name), None)
    if seed_info is None:
        yield f"未找到{seed_name}的信息，可能是数据错误。"
        return

    current_season = get_current_season()
    is_right_season = current_season.get("name") in (seed_info.get("season") or [])

    seed_entry["count"] -= 1
    if seed_entry["count"] <= 0:
        farm["inventory"]["seeds"] = [
            s for s in farm["inventory"]["seeds"] if s is not seed_entry
        ]

    plot.update(
        {
            "crop": seed_name,
            "plantedAt": datetime.now().isoformat(),
            "water": 50,
            "fertility": 40,
            "health": 100,
            "growthStage": 0,
            "harvestReady": False,
        },
    )
    seasonal_note = (
        "（当前是适合种植的季节）"
        if is_right_season
        else "（注意：当前不是适合种植的季节，生长可能较慢）"
    )
    _log(
        farm,
        "种植",
        f"在第{plot_index + 1}号地块种植了{seed_name} {seasonal_note}",
    )
    farm["experience"] = farm.get("experience", 0) + 5
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", "plant")

    path = await renderer.render_image(
        "plant_seed",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "seedName": seed_name,
            "plotIndex": plot_index + 1,
            "growthDays": seed_info.get("growthDays"),
            "isRightSeason": is_right_season,
            "currentSeason": current_season.get("name"),
            "toolName": hoe["name"],
            "toolDurability": hoe["durability"],
            "seedIcon": seed_info.get("icon", "default_seed.png"),
        },
    )
    yield event.image_result(path)


@cmd(r"^#购买农具.*$", name="farm_buy_tools", priority=7)
async def farm_buy_tools(self, event):
    """购买农具（同类别旧工具会被替换）"""
    _require_cd(event, "farm", "buy")
    user_id = sender_id(event)
    player = await _require_player(event)
    farm = await _require_farm(user_id)
    import re

    tool_name = re.sub(r"^#购买农具\s*", "", event.get_message_str()).strip()
    if not tool_name:
        yield "请指定要购买的农具名称，例如：#购买农具 高级锄头"
        return
    tool_info = next((t for t in _tools() if t.get("name") == tool_name), None)
    if tool_info is None:
        yield f'农场商店中没有出售"{tool_name}"，请使用 #农场商店 查看可用工具。'
        return
    if int(player.get("money", 0)) < tool_info["price"]:
        yield f"购买{tool_name}需要{tool_info['price']}金币，你的金币不足！"
        return
    player["money"] = int(player.get("money", 0)) - tool_info["price"]
    from . import base as _guards

    await _guards.save(user_id, player)

    def _category(name: str) -> str:
        return name.split(" ")[1] if " " in name else ""

    same_category = _category(tool_info["name"])
    farm["inventory"]["tools"] = [
        t
        for t in farm["inventory"]["tools"]
        if _category(t.get("name", "")) != same_category or same_category == ""
    ]
    farm["inventory"]["tools"].append(
        {
            "id": tool_info["id"],
            "name": tool_info["name"],
            "durability": tool_info["durability"],
            "efficiency": tool_info["efficiency"],
        },
    )
    _log(
        farm,
        "购买工具",
        f"购买了{tool_info['name']}，花费{tool_info['price']}金币",
    )
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", "buy")

    path = await renderer.render_image(
        "buy_tool",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "toolName": tool_info["name"],
            "toolPrice": tool_info["price"],
            "toolDurability": tool_info["durability"],
            "toolEfficiency": tool_info["efficiency"],
            "toolDescription": tool_info.get(
                "description",
                f"这是一个{tool_info['name']}工具",
            ),
            "userMoney": player["money"],
            "toolIcon": tool_info.get("icon", "default_tool.png"),
        },
    )
    yield event.image_result(path)


@cmd(r"^#购买种子.*$", name="farm_buy_seeds", priority=7)
async def farm_buy_seeds(self, event):
    """购买种子：#购买种子 [种子名称] [数量]"""
    _require_cd(event, "farm", "buy")
    user_id = sender_id(event)
    player = await _require_player(event)
    farm = await _require_farm(user_id)
    import re

    rest = re.sub(r"^#购买种子\s*", "", event.get_message_str()).strip()
    parts = rest.split()
    if not parts:
        yield "命令格式错误，正确格式：#购买种子 [种子名称] [数量(可选)]"
        return
    seed_name = parts[0]
    try:
        quantity = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        quantity = 0
    if quantity <= 0:
        yield "购买数量必须是正整数。"
        return

    seed_info = next((s for s in _seeds() if s.get("name") == seed_name), None)
    if seed_info is None:
        yield f'农场商店中没有出售"{seed_name}"种子，请使用 #农场商店 查看可用种子。'
        return
    total_price = seed_info["price"] * quantity
    if int(player.get("money", 0)) < total_price:
        yield (f"购买{quantity}个{seed_name}种子需要{total_price}金币，你的金币不足！")
        return
    player["money"] = int(player.get("money", 0)) - total_price
    from . import base as _guards

    await _guards.save(user_id, player)

    existing = next(
        (s for s in farm["inventory"]["seeds"] if s["name"] == seed_name),
        None,
    )
    if existing:
        existing["count"] += quantity
    else:
        farm["inventory"]["seeds"].append(
            {
                "name": seed_name,
                "count": quantity,
                "price": seed_info["price"],
                "season": seed_info.get("season"),
            },
        )
    _log(
        farm,
        "购买种子",
        f"购买了{quantity}个{seed_name}种子，花费{total_price}金币",
    )
    await _save_farm_data((await _load_farm_data()) | {user_id: farm})
    set_cd(user_id, "farm", "buy")

    path = await renderer.render_image(
        "buy_seed",
        {
            "cssFile": _css_file(),
            "farmName": farm["name"],
            "seedName": seed_info["name"],
            "seedQuantity": quantity,
            "seedPrice": seed_info["price"],
            "totalPrice": total_price,
            "userMoney": player["money"],
            "seedSeason": "，".join(seed_info.get("season") or []),
            "seedGrowthDays": seed_info.get("growthDays"),
            "seedIcon": seed_info.get("icon", "default_seed.png"),
            "currentSeason": get_current_season().get("name"),
        },
    )
    yield event.image_result(path)


@cmd(r"^#农场商店$", name="farm_shop", priority=7)
async def farm_shop(self, event):
    """浏览农场商店（种子与农具）"""
    _require_cd(event, "farm", "shop")
    user_id = sender_id(event)
    player = await _require_player(event)
    farm = await _require_farm(user_id)
    seeds = _seeds()
    tools = _tools()
    current = get_current_season()
    seasonal = [
        s
        for s in seeds
        if current.get("name") in (s.get("season") or [])
        or "全年" in (s.get("season") or [])
    ]
    others = [
        s
        for s in seeds
        if current.get("name") not in (s.get("season") or [])
        and "全年" not in (s.get("season") or [])
    ]
    set_cd(user_id, "farm", "shop")
    path = await renderer.render_image(
        "farm_shop",
        {
            "cssFile": _css_file(),
            "farmName": farm.get("name"),
            "userName": player.get("name"),
            "userMoney": player.get("money"),
            "seasonalSeeds": seasonal,
            "otherSeeds": others,
            "tools": tools,
            "currentSeason": current.get("name"),
        },
    )
    yield event.image_result(path)
