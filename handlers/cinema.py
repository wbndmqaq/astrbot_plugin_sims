"""电影院系统 - port of ``apps/cinema.js``.

11 commands covering cinema purchase, theater buying/upgrading, movie
rights, scheduling, facilities, staff hire/training, guide and rankings,
plus the hourly revenue settlement cron.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import load_all_users, save_user
from ..core.renderer import renderer
from .base import cmd


def _config() -> dict:
    data = game_data._load("cinema/movies.json")
    return data if isinstance(data, dict) else {}


async def _check(event, action: str) -> dict:
    remaining = cd_remaining(sender_id(event), "cinema", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")
    from . import base as _guards

    return await _guards.require_player(event)


def _require_cinema(data: dict) -> dict:
    cinema = data.get("cinema")
    if not cinema:
        raise CommandError("你还没有电影院！请先使用 #购买电影院 购买一家电影院。")
    return cinema


async def _render(event, template: str, data: dict):
    path = await renderer.render_image(template, data)
    return event.image_result(path)


# ------------------------------------------------------- hourly revenue --
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
                    start = now.replace(
                        hour=int(hour),
                        minute=int(minute),
                        second=0,
                        microsecond=0,
                    )
                except (ValueError, KeyError):
                    continue
                end_ts = start.timestamp() + schedule.get("duration", 0) * 60
                if start.timestamp() <= now.timestamp() <= end_ts:
                    movie = next(
                        (
                            m
                            for m in cinema.get("movies") or []
                            if m.get("id") == schedule.get("movieId")
                        ),
                        None,
                    )
                    if movie is None:
                        continue
                    attendance = min(
                        1.0,
                        movie.get("popularity", 50) / 100
                        + (cinema.get("reputation", 50) - 50) / 100,
                    )
                    viewers = int(theater.get("capacity", 0) * attendance)
                    ticket_revenue = viewers * schedule.get("price", 0)
                    facility_revenue = sum(
                        viewers
                        * schedule.get("price", 0)
                        * (f.get("revenueMultiplier", 1) - 1)
                        for f in cinema.get("facilities") or []
                    )
                    daily_revenue += ticket_revenue + facility_revenue
                    movie["revenue"] = movie.get("revenue", 0) + ticket_revenue
                    movie["viewers"] = movie.get("viewers", 0) + viewers
        cinema["dailyRevenue"] = daily_revenue
        cinema["totalRevenue"] = cinema.get("totalRevenue", 0) + daily_revenue
        user_data["money"] = int(user_data.get("money", 0)) + daily_revenue
        user_data["money"] -= cinema.get("maintenanceCost", 0) + cinema.get(
            "staffCost",
            0,
        )
        reputation_change = int(daily_revenue / 10000 * 0.1)
        cinema["reputation"] = min(
            100,
            max(0, cinema.get("reputation", 50) + reputation_change),
        )
        await save_user(user_id, user_data)


async def _cinema_tick(context) -> None:
    await update_cinema_data()


register_tick(_cinema_tick)


# ------------------------------------------------------------- commands --
@cmd(r"^#购买电影院$", name="cinema_buy", priority=7)
async def cinema_buy(self, event):
    """购买电影院（10万）"""
    user_id = sender_id(event)
    data = await _check(event, "buy")
    if data.get("cinema"):
        yield "你已经拥有一家电影院了！"
        return
    cost = 100000
    if int(data.get("money", 0)) < cost:
        yield f"你的金钱不足，购买电影院需要{cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - cost
    data["cinema"] = {
        "name": f"{data.get('name')}的电影院",
        "theaters": [],
        "movies": [],
        "facilities": [],
        "staff": [],
        "dailyRevenue": 0,
        "totalRevenue": 0,
        "reputation": 50,
        "maintenanceCost": 0,
        "staffCost": 0,
        "lastUpdate": int(time.time() * 1000),
    }
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "buy")
    yield await _render(
        event,
        "cinema_buy",
        {
            "name": data.get("name"),
            "cinemaName": data["cinema"]["name"],
            "cost": cost,
            "money": data["money"],
        },
    )


@cmd(r"^#电影院信息$", name="cinema_info", priority=7)
async def cinema_info(self, event):
    """查看电影院经营状况"""
    user_id = sender_id(event)
    data = await _check(event, "info")
    cinema = _require_cinema(data)
    set_cd(user_id, "cinema", "info")
    yield await _render(
        event,
        "cinema_info",
        {
            "name": data.get("name"),
            "cinemaName": cinema["name"],
            "theaters": cinema.get("theaters"),
            "movies": cinema.get("movies"),
            "facilities": cinema.get("facilities"),
            "staff": cinema.get("staff"),
            "dailyRevenue": cinema.get("dailyRevenue"),
            "totalRevenue": cinema.get("totalRevenue"),
            "reputation": cinema.get("reputation"),
            "maintenanceCost": cinema.get("maintenanceCost"),
            "staffCost": cinema.get("staffCost"),
        },
    )
    yield


@cmd(r"^#购买影厅.*$", name="cinema_buy_theater", priority=7)
async def cinema_buy_theater(self, event):
    """购买影厅：#购买影厅 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "theater")
    cinema = _require_cinema(data)
    theater_type = event.get_message_str().replace("#购买影厅", "").strip()
    theaters = _config().get("theaters") or {}
    if theater_type not in theaters:
        yield f"无效的影厅类型！可选的影厅类型：{'、'.join(theaters.keys())}"
        return
    if any(t["type"] == theater_type for t in cinema.get("theaters") or []):
        yield f"你已经拥有{theaters[theater_type]['name']}了！"
        return
    cost = theaters[theater_type]["cost"]
    if int(data.get("money", 0)) < cost:
        yield f"你的金钱不足，购买{theaters[theater_type]['name']}需要{cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - cost
    theater_name = (
        f"{theaters[theater_type]['name']}{len(cinema.get('theaters') or []) + 1}"
    )
    cinema.setdefault("theaters", []).append(
        {
            "type": theater_type,
            "name": theater_name,
            "capacity": theaters[theater_type]["capacity"],
            "maintenanceCost": theaters[theater_type]["maintenanceCost"],
            "currentMovie": None,
            "schedule": [],
        },
    )
    cinema["maintenanceCost"] = (
        cinema.get("maintenanceCost", 0) + theaters[theater_type]["maintenanceCost"]
    )
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "theater")
    yield await _render(
        event,
        "cinema_theater_buy",
        {
            "name": data.get("name"),
            "theaterName": theater_name,
            "cost": cost,
            "money": data["money"],
            "capacity": theaters[theater_type]["capacity"],
        },
    )
    yield


@cmd(r"^#升级影厅.*$", name="cinema_upgrade_theater", priority=7)
async def cinema_upgrade_theater(self, event):
    """升级影厅：#升级影厅 [名称]"""
    user_id = sender_id(event)
    data = await _check(event, "upgrade")
    cinema = _require_cinema(data)
    theater_name = event.get_message_str().replace("#升级影厅", "").strip()
    theater = next(
        (t for t in cinema.get("theaters") or [] if t["name"] == theater_name),
        None,
    )
    if theater is None:
        yield "未找到指定的影厅！"
        return
    theaters = _config().get("theaters") or {}
    current_cfg = theaters.get(theater["type"]) or {}
    if not current_cfg.get("nextLevel"):
        yield "该影厅已达到最高等级！"
        return
    upgrade_cost = current_cfg["upgradeCost"]
    if int(data.get("money", 0)) < upgrade_cost:
        yield f"你的金钱不足，升级影厅需要{upgrade_cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - upgrade_cost
    old_type = theater["type"]
    theater["type"] = current_cfg["nextLevel"]
    theater["capacity"] = theaters[theater["type"]]["capacity"]
    theater["maintenanceCost"] = theaters[theater["type"]]["maintenanceCost"]
    cinema["maintenanceCost"] = (
        cinema.get("maintenanceCost", 0)
        - theaters[old_type]["maintenanceCost"]
        + theaters[theater["type"]]["maintenanceCost"]
    )
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "upgrade")
    yield await _render(
        event,
        "cinema_theater_upgrade",
        {
            "name": data.get("name"),
            "theaterName": theater["name"],
            "oldType": theaters[old_type]["name"],
            "newType": theaters[theater["type"]]["name"],
            "cost": upgrade_cost,
            "money": data["money"],
            "newCapacity": theater["capacity"],
        },
    )
    yield


@cmd(r"^#购买电影.*$", name="cinema_buy_movie", priority=7)
async def cinema_buy_movie(self, event):
    """购买电影版权：#购买电影 [名称]"""
    user_id = sender_id(event)
    data = await _check(event, "movie")
    cinema = _require_cinema(data)
    movie_title = event.get_message_str().replace("#购买电影", "").strip()
    movies_cfg = _config().get("movies") or {}
    selected = None
    for genre_data in movies_cfg.values():
        for movie in genre_data.get("examples") or []:
            if movie.get("title") == movie_title:
                selected = movie
                break
        if selected:
            break
    if selected is None:
        yield "未找到该电影！"
        return
    if any(m["id"] == selected["id"] for m in cinema.get("movies") or []):
        yield "你已经拥有该电影了！"
        return
    cost = selected["cost"]
    if int(data.get("money", 0)) < cost:
        yield f"你的金钱不足，购买电影需要{cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - cost
    cinema.setdefault("movies", []).append(
        {**selected, "purchaseDate": time.strftime("%Y-%m-%dT%H:%M:%S")},
    )
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "movie")
    yield await _render(
        event,
        "cinema_movie_buy",
        {
            "name": data.get("name"),
            "movieTitle": selected["title"],
            "genre": selected.get("genre"),
            "cost": cost,
            "money": data["money"],
            "rating": selected.get("rating"),
            "popularity": selected.get("popularity"),
        },
    )
    yield


@cmd(r"^#排片.*$", name="cinema_schedule", priority=7)
async def cinema_schedule(self, event):
    """安排放映：#排片 [影厅] [电影] [时间]"""
    user_id = sender_id(event)
    data = await _check(event, "schedule")
    cinema = _require_cinema(data)
    args = event.get_message_str().replace("#排片", "").strip().split()
    if len(args) != 3:
        yield "请按照格式输入：#排片 [影厅名称] [电影名称] [场次时间]"
        return
    theater_name, movie_title, schedule_time = args
    theater = next(
        (t for t in cinema.get("theaters") or [] if t["name"] == theater_name),
        None,
    )
    movie = next(
        (m for m in cinema.get("movies") or [] if m["title"] == movie_title),
        None,
    )
    if theater is None or movie is None:
        yield "未找到指定的影厅或电影！"
        return
    if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", schedule_time):
        yield "请输入正确的时间格式（24小时制，如：14:30）"
        return
    now = datetime.now()
    hour, minute = schedule_time.split(":")
    target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    for existing in theater.get("schedule") or []:
        try:
            e_hour, e_min = existing["time"].split(":")
            existing_ts = now.replace(
                hour=int(e_hour),
                minute=int(e_min),
                second=0,
                microsecond=0,
            ).timestamp()
        except (ValueError, KeyError):
            continue
        if abs(existing_ts - target.timestamp()) < movie.get("duration", 0) * 60:
            yield "该时间段已有其他电影排片！"
            return
    theater.setdefault("schedule", []).append(
        {
            "movieId": movie["id"],
            "movieTitle": movie["title"],
            "time": schedule_time,
            "duration": movie.get("duration"),
            "price": movie.get("basePrice", 40),
        },
    )
    theater["schedule"].sort(key=lambda s: s["time"])
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "schedule")
    yield await _render(
        event,
        "cinema_schedule",
        {
            "name": data.get("name"),
            "theaterName": theater["name"],
            "movieTitle": movie["title"],
            "time": schedule_time,
            "duration": movie.get("duration"),
            "price": movie.get("basePrice", 40),
            "schedule": theater["schedule"],
        },
    )
    yield


@cmd(r"^#购买设施.*$", name="cinema_buy_facility", priority=7)
async def cinema_buy_facility(self, event):
    """购买配套设施：#购买设施 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "facility")
    cinema = _require_cinema(data)
    facility_type = event.get_message_str().replace("#购买设施", "").strip()
    facilities = _config().get("facilities") or {}
    if facility_type not in facilities:
        yield f"无效的设施类型！可选的设施类型：{'、'.join(facilities.keys())}"
        return
    if any(f["type"] == facility_type for f in cinema.get("facilities") or []):
        yield f"你已经拥有{facilities[facility_type]['name']}了！"
        return
    cost = facilities[facility_type]["cost"]
    if int(data.get("money", 0)) < cost:
        yield f"你的金钱不足，购买{facilities[facility_type]['name']}需要{cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - cost
    cinema.setdefault("facilities", []).append(
        {
            "type": facility_type,
            "name": facilities[facility_type]["name"],
            "maintenanceCost": facilities[facility_type]["maintenanceCost"],
            "revenueMultiplier": facilities[facility_type]["revenueMultiplier"],
        },
    )
    cinema["maintenanceCost"] = (
        cinema.get("maintenanceCost", 0) + facilities[facility_type]["maintenanceCost"]
    )
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "facility")
    yield await _render(
        event,
        "cinema_facility_buy",
        {
            "name": data.get("name"),
            "facilityName": facilities[facility_type]["name"],
            "cost": cost,
            "money": data["money"],
            "maintenanceCost": facilities[facility_type]["maintenanceCost"],
            "revenueMultiplier": facilities[facility_type]["revenueMultiplier"],
        },
    )
    yield


@cmd(r"^#雇佣员工.*$", name="cinema_hire_staff", priority=7)
async def cinema_hire_staff(self, event):
    """雇佣影院员工：#雇佣员工 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "hire")
    cinema = _require_cinema(data)
    staff_type = event.get_message_str().replace("#雇佣员工", "").strip()
    staff_cfg = _config().get("staff") or {}
    if staff_type not in staff_cfg:
        yield f"无效的员工类型！可选的员工类型：{'、'.join(staff_cfg.keys())}"
        return
    cost = staff_cfg[staff_type]["salary"]
    if int(data.get("money", 0)) < cost:
        yield f"你的金钱不足，雇佣{staff_cfg[staff_type]['name']}需要{cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - cost
    same_count = sum(1 for s in cinema.get("staff") or [] if s["type"] == staff_type)
    staff_name = f"{staff_cfg[staff_type]['name']}{same_count + 1}"
    cinema.setdefault("staff", []).append(
        {
            "type": staff_type,
            "name": staff_name,
            "level": 1,
            "efficiency": staff_cfg[staff_type]["efficiency"],
            "salary": staff_cfg[staff_type]["salary"],
        },
    )
    cinema["staffCost"] = cinema.get("staffCost", 0) + staff_cfg[staff_type]["salary"]
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "hire")
    yield await _render(
        event,
        "cinema_staff_hire",
        {
            "name": data.get("name"),
            "staffName": staff_name,
            "type": staff_cfg[staff_type]["name"],
            "cost": cost,
            "money": data["money"],
            "level": 1,
            "efficiency": staff_cfg[staff_type]["efficiency"],
        },
    )
    yield


@cmd(r"^#培训员工.*$", name="cinema_train_staff", priority=7)
async def cinema_train_staff(self, event):
    """培训员工提升效率：#培训员工 [名称]"""
    user_id = sender_id(event)
    data = await _check(event, "train")
    cinema = _require_cinema(data)
    args = event.get_message_str().replace("#培训员工", "").strip().split()
    if not args:
        yield "请按照格式输入：#培训员工 [员工名称]"
        return
    staff_name = args[0]
    staff = next(
        (s for s in cinema.get("staff") or [] if s["name"] == staff_name),
        None,
    )
    if staff is None:
        yield "未找到指定的员工！"
        return
    staff_cfg = (_config().get("staff") or {}).get(staff["type"]) or {}
    if staff["level"] >= staff_cfg.get("maxLevel", 5):
        yield "该员工已达到最高等级！"
        return
    training_cost = staff_cfg.get("trainingCost", 1000)
    if int(data.get("money", 0)) < training_cost:
        yield f"你的金钱不足，培训员工需要{training_cost}元。"
        return
    data["money"] = int(data.get("money", 0)) - training_cost
    staff["level"] += 1
    staff["efficiency"] = staff_cfg.get("efficiency", 1) * (1 + staff["level"] * 0.1)
    await save_user(user_id, data)
    set_cd(user_id, "cinema", "train")
    yield await _render(
        event,
        "cinema_staff_train",
        {
            "name": data.get("name"),
            "staffName": staff["name"],
            "oldLevel": staff["level"] - 1,
            "newLevel": staff["level"],
            "cost": training_cost,
            "money": data["money"],
            "efficiency": staff["efficiency"],
        },
    )
    yield


@cmd(r"^#电影院排行榜$", name="cinema_ranking", priority=7)
async def cinema_ranking(self, event):
    """查看电影院经营排行榜"""
    user_id = sender_id(event)
    remaining = cd_remaining(user_id, "cinema", "ranking")
    if remaining > 0:
        raise CommandError(f"数据处理中，请{remaining}秒后再查询")
    cinema_users = []
    for uid, user in (await load_all_users()).items():
        cinema = user.get("cinema")
        if not cinema:
            continue
        cinema_users.append(
            {
                "id": uid,
                "name": user.get("name"),
                "cinemaName": cinema.get("name"),
                "totalRevenue": cinema.get("totalRevenue", 0),
                "reputation": cinema.get("reputation", 0),
                "theaters": len(cinema.get("theaters") or []),
                "movies": len(cinema.get("movies") or []),
            },
        )
    if not cinema_users:
        yield "目前还没有玩家拥有电影院，无法生成排行榜。"
        return
    by_revenue = sorted(cinema_users, key=lambda u: -u["totalRevenue"])[:10]
    by_reputation = sorted(cinema_users, key=lambda u: -u["reputation"])[:10]
    user_ranking = {
        "revenue": next(
            (
                i
                for i, u in enumerate(
                    sorted(cinema_users, key=lambda x: -x["totalRevenue"])
                )
                if u["id"] == user_id
            ),
            -1,
        )
        + 1,
        "reputation": next(
            (
                i
                for i, u in enumerate(
                    sorted(cinema_users, key=lambda x: -x["reputation"])
                )
                if u["id"] == user_id
            ),
            -1,
        )
        + 1,
    }
    yield await _render(
        event,
        "cinema_ranking",
        {
            "revenueRanking": by_revenue,
            "reputationRanking": by_reputation,
            "totalCinemas": len(cinema_users),
            "userRanking": user_ranking,
        },
    )
    set_cd(user_id, "cinema", "ranking")
    yield


@cmd(r"^#电影院攻略$", name="cinema_guide", priority=7)
async def cinema_guide(self, event):
    """查看电影院系统攻略"""
    from ..core.db import check_user

    user = await check_user(sender_id(event))
    yield await _render(
        event,
        "cinema_guide",
        {
            "name": user.get("name")if user else "新玩家",
            "hasCinema": bool(user and user.get("cinema")),
            "commands": [
                {
                    "command": "#购买电影院",
                    "description": "购买一家电影院，开始你的经营生涯",
                },
                {"command": "#电影院信息", "description": "查看你的电影院经营状况"},
                {
                    "command": "#购买影厅 [类型]",
                    "description": "购买新的影厅，可选：small、medium、large、vip",
                },
                {"command": "#升级影厅 [名称]", "description": "升级指定影厅的等级"},
                {"command": "#购买电影 [名称]", "description": "购买新的电影版权"},
                {
                    "command": "#排片 [影厅] [电影] [时间]",
                    "description": "为影厅安排电影放映时间",
                },
                {
                    "command": "#购买设施 [类型]",
                    "description": "购买新的设施，可选：snackBar、drinkBar、restaurant、giftShop",
                },
                {
                    "command": "#雇佣员工 [类型]",
                    "description": "雇佣新的员工，可选：ticketSeller、usher、cleaner、manager",
                },
                {
                    "command": "#培训员工 [名称]",
                    "description": "培训指定员工，提升其效率",
                },
                {"command": "#电影院排行榜", "description": "查看电影院经营排行榜"},
            ],
            "tips": [
                "合理规划影厅数量和类型，满足不同观众需求",
                "及时更新电影片源，保持观众新鲜感",
                "设施和员工的质量会影响收入",
                "注意维护成本和员工成本的控制",
                "声望会影响上座率，要持续提升服务质量",
                "不同时段可以设置不同票价",
            ],
        },
    )
    yield
