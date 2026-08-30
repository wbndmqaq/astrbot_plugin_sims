"""酒馆系统 - port of ``apps/酒馆.js``.

15 commands: create/details/menu/market/supplies/drinks/operate/upgrade/
staff management/ranking/visit, plus the hourly market refresh cron.
Tavern data lives inside the player archive (``userData.tavern``); market
data is a global KV document refreshed hourly.
"""

from __future__ import annotations

import math
import random
import time

from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import check_user, get_store, load_all_users, save_user
from ..core.renderer import renderer
from .base import cmd

TAVERN_KV = "tavern_market"

STAFF_TYPES = [
    {
        "type": "bartender",
        "name": "酒保",
        "salary": 100,
        "levelRequirement": 1,
        "description": "专业调酒师，提高饮品制作效率，降低原料消耗",
        "skills": [
            {"name": "调酒技巧", "description": "制作饮品时减少10%原料消耗"},
            {"name": "花式调酒", "description": "提高饮品价值5%"},
        ],
    },
    {
        "type": "waiter",
        "name": "服务员",
        "salary": 80,
        "levelRequirement": 1,
        "description": "热情的服务员，提高顾客满意度和消费意愿",
        "skills": [
            {"name": "优质服务", "description": "提高顾客满意度5%"},
            {"name": "推销技巧", "description": "增加顾客平均消费3%"},
        ],
    },
    {
        "type": "cleaner",
        "name": "清洁工",
        "salary": 60,
        "levelRequirement": 2,
        "description": "勤劳的清洁工，维持酒馆清洁度，减缓环境恶化",
        "skills": [
            {"name": "环境维护", "description": "每天减少清洁度下降50%"},
            {"name": "整理摆放", "description": "提高酒馆氛围2点"},
        ],
    },
    {
        "type": "security",
        "name": "保安",
        "salary": 120,
        "levelRequirement": 3,
        "description": "魁梧的保安，减少不良事件发生，提高顾客安全感",
        "skills": [
            {"name": "安全管理", "description": "降低不良事件发生概率30%"},
            {"name": "秩序维护", "description": "减少事件负面影响20%"},
        ],
    },
    {
        "type": "musician",
        "name": "驻唱歌手",
        "salary": 200,
        "levelRequirement": 4,
        "description": "有才华的驻唱歌手，大幅提升酒馆氛围和吸引力",
        "skills": [
            {"name": "音乐表演", "description": "提高酒馆氛围10点"},
            {"name": "顾客互动", "description": "提高顾客满意度10%"},
        ],
    },
]


def _css_file() -> str:
    from ..core.renderer import BASE_HREF_DIR

    return BASE_HREF_DIR.as_uri() + "/"


async def _check(event, action: str) -> dict:
    remaining = cd_remaining(sender_id(event), "tavern", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")
    from . import base as _guards

    return await _guards.require_player(event)


def _require_tavern(data: dict) -> dict:
    tavern = data.get("tavern")
    if not tavern:
        raise CommandError("你还没有酒馆！使用 #创建酒馆 [名称] 来创建一家。")
    return tavern


def _initial_market() -> dict:
    return {
        "lastUpdated": time.time(),
        "supplies": [
            {
                "id": "beer_1",
                "name": "普通啤酒",
                "basePrice": 50,
                "price": 50,
                "stock": 100,
                "type": "beer",
                "desc": "最常见的啤酒，适合日常供应",
            },
            {
                "id": "beer_2",
                "name": "精酿啤酒",
                "basePrice": 120,
                "price": 120,
                "stock": 80,
                "type": "beer",
                "desc": "口感独特的精酿啤酒，深受年轻人喜爱",
            },
            {
                "id": "wine_1",
                "name": "红葡萄酒",
                "basePrice": 200,
                "price": 200,
                "stock": 60,
                "type": "wine",
                "desc": "经典红葡萄酒，适合配餐饮用",
            },
            {
                "id": "wine_2",
                "name": "白葡萄酒",
                "basePrice": 180,
                "price": 180,
                "stock": 65,
                "type": "wine",
                "desc": "清爽的白葡萄酒，适合夏季饮用",
            },
            {
                "id": "spirit_1",
                "name": "威士忌",
                "basePrice": 300,
                "price": 300,
                "stock": 40,
                "type": "spirits",
                "desc": "经典烈酒，适合品鉴",
            },
            {
                "id": "spirit_2",
                "name": "伏特加",
                "basePrice": 250,
                "price": 250,
                "stock": 50,
                "type": "spirits",
                "desc": "纯净的烈酒，可调制多种鸡尾酒",
            },
            {
                "id": "food_1",
                "name": "小吃拼盘",
                "basePrice": 80,
                "price": 80,
                "stock": 90,
                "type": "food",
                "desc": "多种小吃组合，适合配酒",
            },
            {
                "id": "food_2",
                "name": "坚果零食",
                "basePrice": 60,
                "price": 60,
                "stock": 100,
                "type": "food",
                "desc": "各类坚果混合，是酒馆必备零食",
            },
            {
                "id": "deco_1",
                "name": "墙面装饰",
                "basePrice": 500,
                "price": 500,
                "stock": 30,
                "type": "decorations",
                "desc": "提升酒馆氛围的墙面装饰",
            },
            {
                "id": "deco_2",
                "name": "桌椅套装",
                "basePrice": 1200,
                "price": 1200,
                "stock": 20,
                "type": "decorations",
                "desc": "舒适的桌椅套装，提升顾客满意度",
            },
        ],
    }


async def _load_market() -> dict:
    data = await get_store().read_kv(TAVERN_KV, None)
    if isinstance(data, dict) and isinstance(data.get("supplies"), list):
        return data
    # 原版 loadTavernMarket：优先读取 data/tavern/tavern_market.json 种子文件
    from ..core import gamedata as game_data

    seeded = game_data._load("tavern/tavern_market.json")
    if isinstance(seeded, dict) and isinstance(seeded.get("supplies"), list):
        seeded.setdefault("lastUpdated", time.time())
        await _save_market(seeded)
        return seeded
    market = _initial_market()
    await _save_market(market)
    return market


async def _save_market(data: dict) -> None:
    await get_store().write_kv(TAVERN_KV, data)


_SPECIAL_SUPPLIES = [
    {
        "id": "special_1",
        "name": "古老威士忌",
        "basePrice": 1500,
        "price": 1500,
        "stock": 10,
        "type": "spirits",
        "desc": "陈年珍藏威士忌，极大提升酒馆声誉",
    },
    {
        "id": "special_2",
        "name": "异域香料",
        "basePrice": 800,
        "price": 800,
        "stock": 15,
        "type": "ingredients",
        "desc": "来自远方的稀有香料，可制作特色饮品",
    },
    {
        "id": "special_3",
        "name": "观赏酒杯套装",
        "basePrice": 2000,
        "price": 2000,
        "stock": 5,
        "type": "decorations",
        "desc": "精美的水晶酒杯，成为酒馆亮点",
    },
    {
        "id": "special_4",
        "name": "顶级音乐盒",
        "basePrice": 2500,
        "price": 2500,
        "stock": 3,
        "type": "decorations",
        "desc": "高品质音乐盒，极大提升酒馆氛围",
    },
    {
        "id": "special_5",
        "name": "传统酿酒设备",
        "basePrice": 5000,
        "price": 5000,
        "stock": 2,
        "type": "equipment",
        "desc": "现场酿酒设备，可吸引特殊顾客",
    },
]


async def update_tavern_market() -> None:
    market = await _load_market()
    supplies = market.get("supplies")
    if not isinstance(supplies, list):
        market = _initial_market()
    else:
        for supply in supplies:
            change = 0.85 + random.random() * 0.3
            supply["price"] = math.floor(supply.get("basePrice", 50) * change)
            supply["stock"] = math.floor(50 + random.random() * 100)
        if random.random() < 0.2:
            special = random.choice(_SPECIAL_SUPPLIES)
            for i, supply in enumerate(market["supplies"]):
                if supply.get("id") == special["id"]:
                    market["supplies"][i] = dict(special)
                    break
            else:
                market["supplies"].append(dict(special))
    await _save_market(market)


async def _market_tick(context) -> None:
    await update_tavern_market()


register_tick(_market_tick)


def _load_events() -> list[dict]:
    from ..core import gamedata as game_data

    data = game_data._load("tavern/tavern_events.json")
    if isinstance(data, dict):
        return data.get("events") or []
    return []


def _get_random_event() -> dict | None:
    events = [e for e in _load_events() if random.random() < 0.3]
    if not events:
        return None
    return random.choice(events)


def _process_event(tavern: dict, event: dict | None) -> dict | None:
    if not event:
        return None
    result = {
        "eventId": event.get("id"),
        "eventName": event.get("name"),
        "description": event.get("description"),
        "income": 0,
        "reputation": 0,
        "customerSatisfaction": 0,
    }
    choices = event.get("choices") or []
    if not choices:
        return result
    choice = random.choice(choices)
    result["choice"] = choice.get("text")
    outcome = choice.get("outcome") or {}
    result["income"] += outcome.get("money", 0) or 0
    result["reputation"] += outcome.get("reputation", 0) or 0
    result["customerSatisfaction"] += outcome.get("customerSatisfaction", 0) or 0
    return result


def _calc_avg_consumption(tavern: dict) -> float:
    base = 30.0
    base += (tavern.get("level", 1) - 1) * 5
    base *= 0.8 + tavern.get("reputation", 3) * 0.04
    base *= 0.8 + tavern.get("atmosphere", 50) / 250
    base *= 0.8 + tavern.get("cleanliness", 100) / 500
    base *= 0.9 + random.random() * 0.2
    return base


def _calc_staff_salary(staff: list[dict]) -> int:
    return sum(s.get("salary", 0) for s in staff or [])


def _calc_drink_sales(drinks: list[dict], customers: int) -> dict:
    sales: dict[str, dict] = {}
    total_popularity = sum(d.get("popularity", 1) for d in drinks) or 1
    for drink in drinks:
        drink_customers = math.floor(
            customers * (drink.get("popularity", 1) / total_popularity)
        )
        purchase_rate = 0.7 + random.random() * 0.3
        quantity = math.floor(drink_customers * purchase_rate)
        sales[drink["id"]] = {
            "name": drink["name"],
            "quantity": quantity,
            "revenue": quantity * drink.get("price", 0),
            "ingredientType": drink.get("ingredientType"),
        }
    return sales


def _consume_supplies(supplies: dict, drink_sales: dict) -> None:
    consumption = {"beer": 0, "wine": 0, "spirits": 0}
    for sale in drink_sales.values():
        ctype = sale.get("ingredientType")
        if ctype in consumption:
            consumption[ctype] += math.ceil(sale["quantity"] / 10)
    for ctype, amount in consumption.items():
        supplies[ctype] = max(0, supplies.get(ctype, 0) - amount)


def _update_drink_popularity(drinks: list[dict], drink_sales: dict) -> None:
    for drink in drinks:
        sale = drink_sales.get(drink["id"])
        if sale:
            drink["sales"] = drink.get("sales", 0) + sale["quantity"]
            if sale["quantity"] > 10:
                change = 0.5
            elif sale["quantity"] > 5:
                change = 0.2
            else:
                change = -0.1
            drink["popularity"] = max(1, min(10, drink.get("popularity", 5) + change))
        else:
            drink["popularity"] = max(1, drink.get("popularity", 5) - 0.3)


def _apply_staff_bonuses(tavern: dict) -> None:
    tavern["staffBonuses"] = {
        "supplySaving": 0,
        "drinkValueBonus": 0,
        "customerSatisfactionBonus": 0,
        "averageConsumptionBonus": 0,
        "cleanlinessDecayReduction": 0,
        "atmosphereBonus": 0,
        "badEventReduction": 0,
        "eventNegativeEffectReduction": 0,
    }
    staff = tavern.get("staff") or []
    for member in staff:
        level = member.get("level", 1) or 1
        mult = 1 + (level - 1) * 0.2
        bonuses = tavern["staffBonuses"]
        if member["type"] == "bartender":
            bonuses["supplySaving"] += 0.1 * mult
            bonuses["drinkValueBonus"] += 0.05 * mult
        elif member["type"] == "waiter":
            bonuses["customerSatisfactionBonus"] += 0.05 * mult
            bonuses["averageConsumptionBonus"] += 0.03 * mult
        elif member["type"] == "cleaner":
            bonuses["cleanlinessDecayReduction"] += 0.5 * mult
            bonuses["atmosphereBonus"] += 2 * mult
        elif member["type"] == "security":
            bonuses["badEventReduction"] += 0.3 * mult
            bonuses["eventNegativeEffectReduction"] += 0.2 * mult
        elif member["type"] == "musician":
            bonuses["atmosphereBonus"] += 10 * mult
            bonuses["customerSatisfactionBonus"] += 0.1 * mult
    b = tavern["staffBonuses"]
    b["supplySaving"] = min(b["supplySaving"], 0.5)
    b["drinkValueBonus"] = min(b["drinkValueBonus"], 0.3)
    b["customerSatisfactionBonus"] = min(b["customerSatisfactionBonus"], 0.5)
    b["averageConsumptionBonus"] = min(b["averageConsumptionBonus"], 0.3)
    b["cleanlinessDecayReduction"] = min(b["cleanlinessDecayReduction"], 0.9)
    b["badEventReduction"] = min(b["badEventReduction"], 0.7)
    b["eventNegativeEffectReduction"] = min(b["eventNegativeEffectReduction"], 0.5)


async def _send_image(event, template: str, data: dict):
    path = await renderer.render_image(template, {"cssFile": _css_file(), **data})
    return event.image_result(path)


# ------------------------------------------------------------- commands --
@cmd(r"^#酒馆系统$", name="tavern_system", priority=7)
async def tavern_system(self, event):
    """酒馆系统总览与攻略"""
    remaining = cd_remaining(sender_id(event), "tavern", "info")
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")
    yield await _send_image(
        event,
        "tavern_system",
        {
            "commands": [
                {"name": "#创建酒馆+名称", "desc": "创建自己的酒馆"},
                {"name": "#酒馆信息", "desc": "查看自己的酒馆详情"},
                {"name": "#酒馆菜单", "desc": "查看酒馆提供的饮品"},
                {"name": "#酒馆市场", "desc": "查看可购买的酒馆物资"},
                {"name": "#购买酒馆物资+ID", "desc": "购买指定的酒馆物资"},
                {"name": "#添加饮品+名称+价格+描述", "desc": "将饮品添加到酒馆菜单"},
                {"name": "#移除饮品+名称", "desc": "从菜单中移除饮品"},
                {"name": "#营业酒馆", "desc": "经营酒馆赚取收益"},
                {"name": "#升级酒馆", "desc": "提升酒馆等级"},
                {"name": "#酒馆员工", "desc": "管理酒馆员工"},
                {"name": "#雇佣员工+类型", "desc": "雇佣新员工"},
                {"name": "#解雇员工+ID", "desc": "解雇现有员工"},
                {"name": "#酒馆排行", "desc": "查看酒馆排行榜"},
                {"name": "#参观酒馆+玩家ID", "desc": "参观其他玩家的酒馆"},
            ],
        },
    )
    set_cd(sender_id(event), "tavern", "info")
    yield (
        "【酒馆系统攻略】\n"
        "1. 系统概述：\n"
        "   - 创建专属酒馆，经营特色饮品\n"
        "   - 升级酒馆提升容量和吸引力\n"
        "   - 雇佣员工提高运营效率\n"
        "   - 定期营业获取收益\n"
        "2. 新手入门：\n"
        '   - 先用"#创建酒馆+名称"创建自己的酒馆\n'
        "   - 在市场购买基础物资\n"
        "   - 添加几款特色饮品到菜单\n"
        '   - 每天使用"#营业酒馆"指令获取收益\n'
        "3. 进阶玩法：\n"
        "   - 根据市场需求调整饮品种类和价格\n"
        "   - 关注特殊活动增加酒馆声望\n"
        "   - 雇佣合适员工提升效率\n"
        "   - 定期升级扩大酒馆规模"
    )


@cmd(r"^#创建酒馆.*$", name="tavern_create", priority=7)
async def tavern_create(self, event):
    """创建酒馆（5000元）：#创建酒馆 [名称]"""
    user_id = sender_id(event)
    data = await _check(event, "create")
    if data.get("tavern"):
        yield "你已经拥有一家酒馆了！"
        return
    initial_cost = 5000
    if int(data.get("money", 0)) < initial_cost:
        yield f"创建酒馆需要{initial_cost}元资金，你的资金不足！"
        return
    tavern_name = event.get_message_str().replace("#创建酒馆", "").strip()
    if not tavern_name:
        yield "请提供酒馆名称！格式：#创建酒馆 [名称]"
        return
    data["money"] = int(data.get("money", 0)) - initial_cost
    data["tavern"] = {
        "name": tavern_name,
        "level": 1,
        "popularity": 10,
        "capacity": 20,
        "cleanliness": 100,
        "atmosphere": 50,
        "drinks": [],
        "supplies": {
            "beer": 20,
            "wine": 10,
            "spirits": 5,
            "food": 15,
            "decorations": 5,
        },
        "staff": [],
        "dailyIncome": 0,
        "totalIncome": 0,
        "lastOperated": None,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "reputation": 3,
        "customerSatisfaction": 80,
        "specialEvents": [],
    }
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "create")
    yield await _send_image(
        event,
        "tavern_created",
        {"tavern": data["tavern"], "cost": initial_cost},
    )
    yield (
        "【新手酒馆攻略】\n"
        "1. 恭喜你成为酒馆老板！接下来：\n"
        '   - 使用"#酒馆市场"查看并购买物资\n'
        '   - 使用"#添加饮品"添加特色饮品到菜单\n'
        '   - 使用"#营业酒馆"开始赚钱\n'
        "2. 经营技巧：\n"
        "   - 保持足够的物资库存\n"
        "   - 定期清洁以维持良好环境\n"
        "   - 根据客户喜好调整饮品种类\n"
        "   - 雇佣员工提高运营效率\n"
        "3. 酒馆升级：\n"
        "   - 提升酒馆等级可增加容量\n"
        "   - 装饰提升氛围，吸引更多顾客\n"
        "   - 名气提升可提高饮品定价"
    )


@cmd(r"^#酒馆信息$", name="tavern_details", priority=7)
async def tavern_details(self, event):
    """查看酒馆详情"""
    user_id = sender_id(event)
    data = await _check(event, "details")
    tavern = _require_tavern(data)
    yield await _send_image(
        event,
        "tavern_details",
        {
            "tavern": tavern,
            "user": {
                "name": data.get("name"),
                "money": data.get("money"),
                "gender": data.get("gender"),
            },
        },
    )
    set_cd(user_id, "tavern", "details")
    yield (
        "【酒馆详情攻略】\n"
        "1. 关键指标解析：\n"
        "   - 人气：影响每日顾客数量\n"
        "   - 容量：决定最大接待能力\n"
        "   - 清洁度：影响顾客满意度\n"
        "   - 氛围：影响顾客消费意愿\n"
        "   - 声誉：影响饮品定价能力\n"
        "2. 提升建议：\n"
        "   - 低人气：添加特色饮品，提升装饰\n"
        "   - 低清洁度：增加清洁次数\n"
        "   - 低氛围：购买装饰物品\n"
        "   - 低声誉：提高饮品质量，举办活动\n"
        "3. 经营周期：\n"
        "   - 定期检查物资库存\n"
        "   - 根据客户反馈调整菜单\n"
        "   - 保持酒馆环境舒适"
    )


@cmd(r"^#酒馆菜单$", name="tavern_menu", priority=7)
async def tavern_menu(self, event):
    """查看酒馆饮品菜单"""
    user_id = sender_id(event)
    data = await _check(event, "menu")
    tavern = _require_tavern(data)
    drinks = tavern.get("drinks") or []
    if not drinks:
        yield "你的酒馆菜单还是空的！使用 #添加饮品 [名称] [价格] [描述] 来添加饮品。"
        return
    yield await _send_image(
        event, "tavern_menu", {"tavern": tavern, "tavernName": tavern["name"]}
    )
    set_cd(user_id, "tavern", "menu")
    yield (
        "【酒馆菜单攻略】\n"
        "1. 菜单设计技巧：\n"
        "   - 提供多种类型饮品以满足不同需求\n"
        "   - 设置合理价格，考虑成本和顾客接受度\n"
        "   - 添加特色饮品提高酒馆辨识度\n"
        "2. 饮品类别建议：\n"
        "   - 基础啤酒：价格亲民，吸引普通顾客\n"
        "   - 精酿啤酒：中等价格，提供特色口味\n"
        "   - 葡萄酒：中高价格，适合追求品质顾客\n"
        "   - 烈酒：高价格，提高单次消费金额\n"
        "   - 特调鸡尾酒：高价格，提升酒馆特色\n"
        "3. 菜单优化：\n"
        "   - 定期调整菜单以适应市场需求\n"
        "   - 移除销量低的饮品\n"
        "   - 根据季节添加应景饮品"
    )


@cmd(r"^#酒馆市场$", name="tavern_market", priority=7)
async def tavern_market(self, event):
    """查看酒馆物资市场行情"""
    user_id = sender_id(event)
    data = await _check(event, "market")
    _require_tavern(data)
    market = await _load_market()
    yield await _send_image(
        event,
        "tavern_market",
        {"market": market, "userMoney": data.get("money")},
    )
    set_cd(user_id, "tavern", "market")
    yield (
        "【酒馆市场攻略】\n"
        "1. 物资购买指南：\n"
        "   - 啤酒：基础饮品，需求量大\n"
        "   - 葡萄酒：中高端饮品，利润较高\n"
        "   - 烈酒：高端饮品，消耗慢利润高\n"
        "   - 食材：提供小吃增加顾客停留时间\n"
        "   - 装饰：提升酒馆氛围和吸引力\n"
        "2. 进货策略：\n"
        "   - 关注市场价格波动，低价时多囤货\n"
        "   - 根据酒馆规模合理控制库存\n"
        "   - 优先保证热销饮品的原料充足\n"
        "3. 特殊物资：\n"
        "   - 限时供应的稀有物资可大幅提升酒馆特色\n"
        "   - 季节性物资可用于制作应景饮品\n"
        "   - 高级装饰可显著提升酒馆氛围"
    )


@cmd(r"^#购买酒馆物资.*$", name="tavern_buy_supplies", priority=7)
async def tavern_buy_supplies(self, event):
    """购买酒馆物资：#购买酒馆物资 [物资ID] [数量]"""
    user_id = sender_id(event)
    data = await _check(event, "buy")
    tavern = _require_tavern(data)
    params = event.get_message_str().replace("#购买酒馆物资", "").strip().split()
    if not params:
        yield "请指定要购买的物资ID！格式：#购买酒馆物资 [物资ID] [数量(可选)]"
        return
    supply_id = params[0]
    try:
        quantity = int(params[1]) if len(params) > 1 else 1
    except ValueError:
        quantity = 0
    if quantity <= 0:
        yield "购买数量必须为正整数！"
        return
    market = await _load_market()
    supply = next(
        (s for s in market.get("supplies", []) if s.get("id") == supply_id), None
    )
    if supply is None:
        yield "未找到该物资，请检查ID是否正确！"
        return
    if supply.get("stock", 0) < quantity:
        yield f"市场库存不足！当前仅有{supply['stock']}份该物资。"
        return
    total_price = supply["price"] * quantity
    if int(data.get("money", 0)) < total_price:
        yield f"你的资金不足！购买{quantity}份{supply['name']}需要{total_price}元。"
        return
    data["money"] = int(data.get("money", 0)) - total_price
    tavern.setdefault("supplies", {})
    stype = supply.get("type", "beer")
    tavern["supplies"][stype] = tavern["supplies"].get(stype, 0) + quantity
    supply["stock"] -= quantity
    await _save_market(market)
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "buy")
    yield await _send_image(
        event,
        "tavern_purchase",
        {
            "supply": supply,
            "quantity": quantity,
            "totalPrice": total_price,
            "tavern": tavern,
        },
    )
    yield (
        "【物资购买攻略】\n"
        f"1. 物资用途：\n   - {supply['name']}({stype}类)：{supply.get('desc', '')}\n"
        "   - 不同类型物资影响酒馆不同方面\n"
        "2. 购买建议：\n"
        "   - 关注价格波动，低价时多囤货\n"
        "   - 保持适量库存，避免物资不足\n"
        "   - 特殊物资出现时优先考虑购买\n"
        "3. 库存管理：\n"
        "   - 定期检查物资消耗情况\n"
        "   - 根据顾客需求调整采购计划\n"
        "   - 合理分配资金，均衡发展酒馆"
    )


@cmd(r"^#添加饮品.*$", name="tavern_add_drink", priority=7)
async def tavern_add_drink(self, event):
    """调制新饮品上架：#添加饮品 [名称] [价格] [原料类型] [描述]"""
    user_id = sender_id(event)
    data = await _check(event, "addDrink")
    tavern = _require_tavern(data)
    params = event.get_message_str().replace("#添加饮品", "").strip().split()
    if len(params) < 4:
        yield "参数不足！格式：#添加饮品 [名称] [价格] [原料类型(beer/wine/spirits)] [描述]"
        return
    drink_name = params[0]
    try:
        drink_price = int(params[1])
    except ValueError:
        drink_price = 0
    ingredient_type = params[2].lower()
    drink_desc = " ".join(params[3:])
    if drink_price <= 0:
        yield "价格必须为正整数！"
        return
    if ingredient_type not in {"beer", "wine", "spirits"}:
        yield "无效的原料类型！可用类型: beer, wine, spirits"
        return
    supplies = tavern.setdefault("supplies", {})
    if supplies.get(ingredient_type, 0) < 1:
        yield f"你的酒馆缺少{ingredient_type}类原料，请先购买物资！"
        return
    drinks = tavern.setdefault("drinks", [])
    if any(d.get("name") == drink_name for d in drinks):
        yield "菜单中已有同名饮品！请使用其他名称。"
        return
    max_drinks = 10 + (tavern.get("level", 1) - 1) * 2
    if len(drinks) >= max_drinks:
        yield f"菜单已满！当前等级最多提供{max_drinks}种饮品。升级酒馆可增加菜单容量。"
        return
    new_drink = {
        "id": f"custom_{int(time.time() * 1000):x}",
        "name": drink_name,
        "price": drink_price,
        "basePrice": drink_price,
        "ingredientType": ingredient_type,
        "description": drink_desc,
        "popularity": 5,
        "sales": 0,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    drinks.append(new_drink)
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "addDrink")
    yield await _send_image(
        event,
        "tavern_add_drink",
        {"drink": new_drink, "tavernName": tavern["name"]},
    )
    yield (
        "【饮品添加攻略】\n"
        "1. 饮品设计技巧：\n"
        "   - 饮品名称要有特色，易于记忆\n"
        "   - 价格要考虑成本和顾客接受度\n"
        "   - 描述要生动，突出特色和卖点\n"
        "2. 不同饮品类型特点：\n"
        "   - 啤酒类：价格亲民，销量大，利润小\n"
        "   - 葡萄酒类：中档价格，适合搭配食物\n"
        "   - 烈酒类：高价，消耗慢，利润高\n"
        "3. 菜单管理：\n"
        "   - 定期关注各饮品销量和顾客反馈\n"
        "   - 移除销量低的饮品，增加新品种\n"
        "   - 根据酒馆客户群体调整饮品组合"
    )


@cmd(r"^#移除饮品.*$", name="tavern_remove_drink", priority=7)
async def tavern_remove_drink(self, event):
    """下架饮品：#移除饮品 [名称]"""
    user_id = sender_id(event)
    data = await _check(event, "removeDrink")
    tavern = _require_tavern(data)
    drinks = tavern.get("drinks") or []
    if not drinks:
        yield "你的酒馆菜单是空的，没有饮品可以移除！"
        return
    drink_name = event.get_message_str().replace("#移除饮品", "").strip()
    if not drink_name:
        yield "请指定要移除的饮品名称！格式：#移除饮品 [名称]"
        return
    removed = next((d for d in drinks if d.get("name") == drink_name), None)
    if removed is None:
        yield f'未找到名为"{drink_name}"的饮品！请检查拼写或使用#酒馆菜单查看现有饮品。'
        return
    drinks.remove(removed)
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "removeDrink")
    yield await _send_image(
        event,
        "tavern_remove_drink",
        {
            "drink": removed,
            "tavernName": tavern["name"],
            "remainingDrinks": len(drinks),
        },
    )
    yield (
        "【饮品移除攻略】\n"
        "1. 移除时机：\n"
        "   - 销量长期不佳的饮品应及时移除\n"
        "   - 季节性饮品结束时应更换\n"
        "   - 随着酒馆调整风格可更新菜单\n"
        "2. 菜单优化：\n"
        "   - 保持菜单精简，避免选择困难\n"
        "   - 确保各类饮品都有覆盖\n"
        "   - 突出特色和高利润饮品\n"
        "3. 替换建议：\n"
        "   - 移除后可添加新饮品填补空缺\n"
        "   - 根据顾客反馈调整新饮品类型\n"
        "   - 考虑提供限时特饮增加新鲜感"
    )


@cmd(r"^#营业酒馆$", name="tavern_operate", priority=7)
async def tavern_operate(self, event):
    """营业酒馆结算当日收益"""
    user_id = sender_id(event)
    data = await _check(event, "operate")
    tavern = _require_tavern(data)
    drinks = tavern.get("drinks") or []
    if not drinks:
        yield "你的酒馆菜单是空的！使用 #添加饮品 命令添加至少一种饮品才能营业。"
        return
    supplies = tavern.setdefault("supplies", {})
    insufficient = [t for t in ("beer", "wine", "spirits") if supplies.get(t, 0) < 2]
    if insufficient:
        yield f"酒馆缺少必要的物资：{', '.join(insufficient)}，请前往酒馆市场购买！"
        return
    today = time.strftime("%Y-%m-%d")
    last = tavern.get("lastOperated")
    if (
        last
        and time.strftime(
            "%Y-%m-%d",
            time.localtime(time.mktime(time.strptime(last[:10], "%Y-%m-%d"))),
        )
        == today
    ):
        yield "今天已经营业过了，请明天再来！"
        return

    base_customers = math.floor(
        tavern.get("popularity", 10) * (0.9 + random.random() * 0.2)
    )
    max_customers = tavern.get("capacity", 20)
    customers = min(base_customers, max_customers)
    avg_consumption = _calc_avg_consumption(tavern)
    income = math.floor(customers * avg_consumption)
    staff_salary = _calc_staff_salary(tavern.get("staff") or [])
    profit = income - staff_salary
    event_data = _get_random_event()
    event_result = _process_event(tavern, event_data)
    drink_sales = _calc_drink_sales(drinks, customers)
    _consume_supplies(supplies, drink_sales)
    tavern["lastOperated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tavern["dailyIncome"] = profit
    tavern["totalIncome"] = tavern.get("totalIncome", 0) + profit
    _update_drink_popularity(drinks, drink_sales)
    tavern["cleanliness"] = max(0, tavern.get("cleanliness", 100) - 15)
    if tavern["cleanliness"] < 30:
        tavern["reputation"] = max(1, tavern.get("reputation", 3) - 1)
    if event_result:
        tavern["reputation"] = max(
            1,
            min(
                10, tavern.get("reputation", 3) + (event_result.get("reputation") or 0)
            ),
        )
        income += event_result.get("income") or 0
        tavern["customerSatisfaction"] = max(
            0,
            min(
                100,
                tavern.get("customerSatisfaction", 80)
                + (event_result.get("customerSatisfaction") or 0),
            ),
        )
    data["money"] = int(data.get("money", 0)) + profit
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "operate")
    yield await _send_image(
        event,
        "tavern_operation",
        {
            "tavern": tavern,
            "operationResult": {
                "customers": customers,
                "avgConsumption": round(avg_consumption, 2),
                "income": income,
                "staffSalary": staff_salary,
                "profit": profit,
                "drinkSales": drink_sales,
                "event": event_data,
                "eventResult": event_result,
            },
        },
    )
    clean_hint = (
        "清洁度较低，需及时清理环境"
        if tavern["cleanliness"] < 50
        else "保持良好的清洁度可提高顾客满意度"
    )
    rep_hint = (
        "提高酒馆声誉可增加客单价"
        if tavern.get("reputation", 3) < 5
        else "声誉良好，可适当提高饮品价格"
    )
    yield (
        "【酒馆经营攻略】\n"
        f"1. 营业数据分析：\n"
        f"   - 客流量{customers}人（最大容量{max_customers}人）\n"
        f"   - 人均消费{avg_consumption:.2f}元\n"
        f"   - 总收入{income}元，员工支出{staff_salary}元\n"
        f"   - 净利润{profit}元\n"
        "2. 提升建议：\n"
        f"   - {'客流量接近上限，考虑升级酒馆扩大容量' if customers >= max_customers * 0.9 else '提高人气可增加客流量'}\n"
        f"   - {clean_hint}\n"
        f"   - {rep_hint}\n"
        "3. 物资管理：\n"
        "   - 定期检查物资库存，确保不会中断营业\n"
        "   - 关注畅销饮品对应原料的消耗速度\n"
        "   - 物资价格波动时及时调整采购策略"
    )


@cmd(r"^#(?:升级酒馆|酒馆升级)$", name="tavern_upgrade", priority=7)
async def tavern_upgrade(self, event):
    """升级酒馆（容量+10/氛围+5/声誉+1）"""
    user_id = sender_id(event)
    data = await _check(event, "upgrade")
    tavern = _require_tavern(data)
    current_level = tavern.get("level", 1)
    max_level = 10
    if current_level >= max_level:
        yield f"你的酒馆已经达到最高等级({max_level})了！"
        return
    upgrade_cost = 5000 * (2 ** (current_level - 1))
    if int(data.get("money", 0)) < upgrade_cost:
        yield f"升级酒馆到{current_level + 1}级需要{upgrade_cost}元，你的资金不足！"
        return
    prev_capacity = tavern.get("capacity", 20)
    data["money"] = int(data.get("money", 0)) - upgrade_cost
    tavern["level"] = current_level + 1
    tavern["capacity"] = prev_capacity + 10
    tavern["atmosphere"] = tavern.get("atmosphere", 50) + 5
    tavern["reputation"] = min(10, tavern.get("reputation", 3) + 1)
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "upgrade")
    yield await _send_image(
        event,
        "tavern_upgrade",
        {
            "tavern": tavern,
            "upgradeCost": upgrade_cost,
            "prevLevel": current_level,
            "prevCapacity": prev_capacity,
            "capacityIncrease": tavern["capacity"] - prev_capacity,
        },
    )
    yield (
        "【酒馆升级攻略】\n"
        "1. 升级收益：\n"
        f"   - 容量增加：从{prev_capacity}人提升到{tavern['capacity']}人\n"
        "   - 酒馆氛围提升5点\n"
        "   - 酒馆声誉提升1点\n"
        "   - 菜单容量增加2个位置\n"
        "2. 升级建议：\n"
        "   - 酒馆客流量接近容量上限时优先考虑升级\n"
        "   - 资金充足时尽早升级以提高收益空间\n"
        "   - 升级同时注意补充物资和更新菜单\n"
        "3. 等级规划：\n"
        "   - 1-3级：专注增加基础饮品和积累资金\n"
        "   - 4-6级：提高饮品多样性，开始雇佣员工\n"
        "   - 7-10级：打造高端酒馆，提供特色体验"
    )


@cmd(r"^#酒馆员工$", name="tavern_staff", priority=7)
async def tavern_staff(self, event):
    """查看酒馆员工管理面板"""
    user_id = sender_id(event)
    data = await _check(event, "staffView")
    tavern = _require_tavern(data)
    staff = tavern.setdefault("staff", [])
    yield await _send_image(
        event,
        "tavern_staff",
        {
            "tavern": tavern,
            "currentStaff": staff,
            "availableStaff": STAFF_TYPES,
            "userMoney": data.get("money"),
        },
    )
    set_cd(user_id, "tavern", "staffView")
    yield (
        "【员工管理攻略】\n"
        "1. 员工类型与作用：\n"
        "   - 酒保：提高饮品制作效率，降低原料消耗\n"
        "   - 服务员：提高顾客满意度和消费意愿\n"
        "   - 清洁工：维持酒馆清洁度，减缓环境恶化\n"
        "   - 保安：减少不良事件发生，提高顾客安全感\n"
        "   - 驻唱歌手：大幅提升酒馆氛围和吸引力\n"
        "2. 雇佣策略：\n"
        "   - 低级酒馆优先雇佣酒保和服务员\n"
        "   - 中级酒馆需要清洁工维持环境\n"
        "   - 高级酒馆添加特色员工提升体验\n"
        "3. 薪资管理：\n"
        "   - 员工工资会从每日营业收入中扣除\n"
        "   - 合理控制员工数量避免支出过高\n"
        "   - 选择性价比高的员工类型优先雇佣"
    )


@cmd(r"^#雇佣员工.*$", name="tavern_hire_staff", priority=7)
async def tavern_hire_staff(self, event):
    """雇佣员工：#雇佣员工 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "staffHire")
    tavern = _require_tavern(data)
    staff = tavern.setdefault("staff", [])
    staff_type = event.get_message_str().replace("#雇佣员工", "").strip().lower()
    if not staff_type:
        yield "请指定要雇佣的员工类型！格式：#雇佣员工 [类型]"
        return
    info = next(
        (
            s
            for s in STAFF_TYPES
            if s["type"].lower() == staff_type or s["name"] == staff_type
        ),
        None,
    )
    if info is None:
        yield (
            f"未找到员工类型: {staff_type}！可用类型: {', '.join(s['type'] for s in STAFF_TYPES)}"
        )
        return
    if tavern.get("level", 1) < info["levelRequirement"]:
        yield (
            f"雇佣{info['name']}需要酒馆等级达到{info['levelRequirement']}级！"
            f"当前等级: {tavern.get('level', 1)}级"
        )
        return
    if any(s["type"] == info["type"] for s in staff):
        yield f"你已经雇佣了{info['name']}！同类型员工只能雇佣一名。"
        return
    max_staff = min(5, tavern.get("level", 1))
    if len(staff) >= max_staff:
        yield f"酒馆员工已达上限({max_staff}名)！升级酒馆可增加员工上限。"
        return
    hire_cost = info["salary"] * 5
    if int(data.get("money", 0)) < hire_cost:
        yield f"雇佣{info['name']}需要{hire_cost}元(包含5天工资)，你的资金不足！"
        return
    surnames = "王李张刘陈杨赵黄周吴徐孙马朱胡林郭何高罗"
    given = "明芳军华超燕娜强玲杰丽涛静磊敏刚霞浩颖鹏"
    random_name = random.choice(surnames) + random.choice(given)
    new_staff = {
        "id": f"staff_{int(time.time() * 1000):x}",
        "name": random_name,
        "type": info["type"],
        "salary": info["salary"],
        "skills": list(info["skills"]),
        "hiredAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "level": 1,
        "experience": 0,
    }
    data["money"] = int(data.get("money", 0)) - hire_cost
    staff.append(new_staff)
    _apply_staff_bonuses(tavern)
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "staffHire")
    yield await _send_image(
        event,
        "tavern_hire_staff",
        {"tavern": tavern, "newStaff": new_staff, "hireCost": hire_cost},
    )
    skill_lines = "\n   ".join(
        f"- {s['name']}: {s['description']}" for s in info["skills"]
    )
    yield (
        "【雇佣员工攻略】\n"
        f"1. {info['name']}的作用：\n   {info['description']}\n"
        f"2. 相关技能：\n   {skill_lines}\n"
        "3. 管理建议：\n"
        "   - 员工每天工作会增加经验，经验满后可升级\n"
        "   - 升级后技能效果提升，但薪资也会增加\n"
        "   - 合理安排员工数量，控制人力成本"
    )


@cmd(r"^#解雇员工.*$", name="tavern_fire_staff", priority=7)
async def tavern_fire_staff(self, event):
    """解雇员工：#解雇员工 [ID]"""
    user_id = sender_id(event)
    data = await _check(event, "staffFire")
    tavern = _require_tavern(data)
    staff = tavern.setdefault("staff", [])
    if not staff:
        yield "你的酒馆还没有雇佣任何员工！"
        return
    staff_id = event.get_message_str().replace("#解雇员工", "").strip()
    if not staff_id:
        yield "请指定要解雇的员工ID！格式：#解雇员工 [ID]。可通过 #酒馆员工 查看员工ID。"
        return
    fired = next((s for s in staff if s.get("id") == staff_id), None)
    if fired is None:
        yield f"未找到ID为{staff_id}的员工！请使用 #酒馆员工 查看正确的员工ID。"
        return
    staff.remove(fired)
    _apply_staff_bonuses(tavern)
    await save_user(user_id, data)
    set_cd(user_id, "tavern", "staffFire")
    yield await _send_image(
        event, "tavern_fire_staff", {"tavern": tavern, "firedStaff": fired}
    )
    yield (
        "【解雇员工攻略】\n"
        f"1. 解雇影响：\n   - 失去{fired['name']}的技能加成\n"
        f"   - 节省每日{fired['salary']}元工资开支\n"
        "   - 可雇佣新员工填补空缺\n"
        "2. 合理调整：\n"
        "   - 定期评估员工绩效和薪资性价比\n"
        "   - 根据酒馆经营重点调整员工配置\n"
        "   - 高级酒馆应保持完整的员工团队\n"
        "3. 后续建议：\n"
        "   - 考虑雇佣其他类型员工补充技能\n"
        "   - 优先雇佣适合当前经营阶段的员工\n"
        "   - 控制人力成本与收益平衡"
    )


@cmd(r"^#酒馆排行$", name="tavern_ranking", priority=7)
async def tavern_ranking(self, event):
    """查看酒馆排行榜（等级/人气/收入）"""
    user_id = sender_id(event)
    data = await _check(event, "ranking")
    owners = []
    for uid, user in (await load_all_users()).items():
        tavern = user.get("tavern")
        if not tavern:
            continue
        owners.append(
            {
                "userId": uid,
                "playerName": user.get("name"),
                "tavernName": tavern.get("name"),
                "level": tavern.get("level", 1),
                "popularity": tavern.get("popularity", 0),
                "reputation": tavern.get("reputation", 0),
                "totalIncome": tavern.get("totalIncome", 0),
                "drinkCount": len(tavern.get("drinks") or []),
                "staffCount": len(tavern.get("staff") or []),
            },
        )
    if not owners:
        yield "目前还没有玩家拥有酒馆！"
        return
    by_level = sorted(owners, key=lambda t: -t["level"])
    by_popularity = sorted(owners, key=lambda t: -t["popularity"])
    by_income = sorted(owners, key=lambda t: -t["totalIncome"])
    user_rankings = None
    if data.get("tavern"):
        user_rankings = {
            "byLevel": next(
                (i for i, t in enumerate(by_level) if t["userId"] == user_id), -1
            )
            + 1,
            "byPopularity": next(
                (i for i, t in enumerate(by_popularity) if t["userId"] == user_id), -1
            )
            + 1,
            "byIncome": next(
                (i for i, t in enumerate(by_income) if t["userId"] == user_id), -1
            )
            + 1,
        }
    yield await _send_image(
        event,
        "tavern_ranking",
        {
            "rankings": {
                "byLevel": by_level[:10],
                "byPopularity": by_popularity[:10],
                "byIncome": by_income[:10],
            },
            "userRankings": user_rankings,
            "totalTaverns": len(owners),
        },
    )
    set_cd(user_id, "tavern", "ranking")
    yield (
        "【酒馆排行攻略】\n"
        "1. 排行榜分类：\n"
        "   - 等级排行：反映酒馆规模和发展阶段\n"
        "   - 人气排行：反映顾客喜爱程度和客流量\n"
        "   - 收入排行：反映经营效益和累计盈利\n"
        "2. 提升排名策略：\n"
        "   - 等级排名：积极升级酒馆\n"
        "   - 人气排名：提供特色饮品，保持良好环境\n"
        "   - 收入排名：高效经营，控制成本\n"
        "3. 参观技巧：\n"
        '   - 使用"#参观酒馆+玩家ID"参观其他酒馆\n'
        "   - 学习高排名酒馆的经营模式\n"
        "   - 关注特色饮品和员工配置"
    )


@cmd(r"^#参观酒馆.*$", name="tavern_visit", priority=7)
async def tavern_visit(self, event):
    """参观其他玩家的酒馆（+1人气）"""
    user_id = sender_id(event)
    data = await _check(event, "visit")
    target_id = event.get_message_str().replace("#参观酒馆", "").strip()
    if not target_id:
        yield "请指定要参观的玩家ID！格式：#参观酒馆 [玩家ID]。可通过 #酒馆排行 查看玩家ID。"
        return
    if target_id == user_id:
        yield "不能参观自己的酒馆，请使用 #酒馆信息 查看自己的酒馆。"
        return
    target = await check_user(target_id)
    if target is None:
        yield "未找到该玩家！请检查ID是否正确。"
        return
    tavern = target.get("tavern")
    if not tavern:
        yield f"玩家 {target.get('name')} 还没有创建酒馆！"
        return
    tavern["popularity"] = min(100, tavern.get("popularity", 0) + 1)
    await save_user(target_id, target)
    yield await _send_image(
        event,
        "tavern_visit",
        {
            "targetUser": {"id": target_id, "name": target.get("name")},
            "tavern": tavern,
            "visitor": {"id": user_id, "name": data.get("name")},
        },
    )
    set_cd(user_id, "tavern", "visit")
    yield (
        "【酒馆参观攻略】\n"
        "1. 学习要点：\n"
        "   - 分析该酒馆的规模、菜单和员工配置\n"
        "   - 观察特色饮品的种类和定价策略\n"
        "   - 了解酒馆装修和氛围营造方式\n"
        "2. 经营借鉴：\n"
        "   - 成功酒馆通常有合理的资源分配\n"
        "   - 特色鲜明的菜单更容易吸引顾客\n"
        "   - 员工配置要根据酒馆定位调整\n"
        "3. 互动效果：\n"
        "   - 你的参观为对方酒馆增加了1点人气\n"
        "   - 多参观可以学习不同经营风格\n"
        "   - 交流经验有助于共同提高"
    )
