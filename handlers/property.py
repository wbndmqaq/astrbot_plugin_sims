"""房产系统 - port of ``apps/房产系统.js``.

Market browsing/filtering, buy/sell with renovation & condition bonuses,
renovation levels, renting with hourly income, plus the hourly market
fluctuation cron.
"""

from __future__ import annotations

import random
import time
from typing import Any

from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import get_store, save_user
from ..core.renderer import renderer
from .base import cmd

MARKET_KV = "real_estate_market"

PROPERTY_TYPES = ["公寓", "别墅", "商铺", "写字楼", "住宅"]
LOCATIONS = ["市中心", "郊区", "商业区", "住宅区", "学区"]

LOCATION_ADJECTIVES = {
    "市中心": ["繁华", "中央", "核心", "高端", "豪华"],
    "郊区": ["宁静", "远景", "自然", "清新", "田园"],
    "商业区": ["商贸", "商务", "经济", "贸易", "金融"],
    "住宅区": ["温馨", "舒适", "宜居", "家庭", "生活"],
    "学区": ["学府", "书香", "教育", "人文", "知识"],
}
TYPE_ADJECTIVES = {
    "公寓": ["现代", "精致", "简约", "便捷", "时尚"],
    "别墅": ["豪华", "尊贵", "奢华", "高雅", "幽静"],
    "商铺": ["繁忙", "旺铺", "黄金", "旗舰", "热门"],
    "写字楼": ["办公", "企业", "高效", "商务", "专业"],
    "住宅": ["家园", "温馨", "舒适", "理想", "幸福"],
}
POSSIBLE_FEATURES = [
    "靠近地铁",
    "临近公园",
    "河景房",
    "临街",
    "南北通透",
    "步行街",
    "商圈中心",
    "学校附近",
    "医院附近",
    "安静社区",
    "精装修",
    "拎包入住",
    "新小区",
    "成熟社区",
    "低密度",
    "高楼层",
    "电梯房",
    "花园洋房",
    "复式结构",
    "地暖",
]
RENOVATION_COSTS = {1: 50000, 2: 100000, 3: 200000, 4: 400000, 5: 800000}


def _generate_new_property() -> dict:
    location = random.choice(LOCATIONS)
    prop_type = random.choice(PROPERTY_TYPES)
    location_adj = random.choice(LOCATION_ADJECTIVES[location])
    type_adj = random.choice(TYPE_ADJECTIVES[prop_type])
    name_format = random.randint(0, 2)
    if name_format == 0:
        name = f"{location_adj}{location}{prop_type}"
    elif name_format == 1:
        name = f"{location}{type_adj}{prop_type}"
    else:
        name = f"{location_adj}{type_adj}{prop_type}"

    base_price = 100000.0
    location_factors = {
        "市中心": 2.2,
        "商业区": 1.7,
        "学区": 1.5,
        "住宅区": 1.3,
        "郊区": 0.8,
    }
    type_factors = {"别墅": 2.5, "商铺": 2.0, "写字楼": 1.8, "公寓": 1.3, "住宅": 1.0}
    base_price *= location_factors[location]
    base_price *= type_factors[prop_type]

    size = int(50 + random.random() * 200)
    features = random.sample(POSSIBLE_FEATURES, 2 + random.randint(0, 2))
    feature_bonus = 1.0
    for feature in features:
        if feature in {"靠近地铁", "临近公园", "河景房", "南北通透", "商圈中心"}:
            feature_bonus += 0.05
    final_price = int(
        base_price * (size / 100) * feature_bonus * (0.85 + random.random() * 0.3),
    )
    return {
        "id": f"{random.getrandbits(36):09x}"[:9],
        "name": name,
        "location": location,
        "type": prop_type,
        "price": final_price,
        "size": size,
        "condition": 100,
        "renovationLevel": 0,
        "features": features,
    }


async def _load_market() -> dict[str, Any]:
    data = await get_store().read_kv(MARKET_KV, None)
    if isinstance(data, dict) and data.get("properties"):
        return data
    market = {"properties": [_generate_new_property() for _ in range(20)]}
    await _save_market(market)
    return market


async def _save_market(data: dict) -> None:
    await get_store().write_kv(MARKET_KV, data)


async def update_real_estate_market() -> None:
    market = await _load_market()
    trend_roll = random.random()
    if trend_roll < 0.2:
        trend_factor = -0.08
    elif trend_roll < 0.7:
        trend_factor = 0.0
    elif trend_roll < 0.95:
        trend_factor = 0.08
    else:
        trend_factor = 0.15
    type_factors = {t: random.random() * 0.06 - 0.03 for t in PROPERTY_TYPES}
    type_factors["别墅"] = random.random() * 0.08 - 0.04
    type_factors["商铺"] = random.random() * 0.10 - 0.05
    type_factors["写字楼"] = random.random() * 0.09 - 0.045
    location_factors = {loc: random.random() * 0.04 - 0.02 for loc in LOCATIONS}
    location_factors["市中心"] = random.random() * 0.08 - 0.02
    location_factors["商业区"] = random.random() * 0.07 - 0.025
    location_factors["郊区"] = random.random() * 0.04 - 0.03
    for prop in market["properties"]:
        change = trend_factor + type_factors.get(prop["type"], 0)
        change += location_factors.get(prop["location"], 0)
        change += random.random() * 0.04 - 0.02
        prop["price"] = max(10000, int(prop["price"] * (1 + change)))
    if random.random() < 0.5:
        for _ in range(random.randint(1, 3)):
            market["properties"].append(_generate_new_property())
    if len(market["properties"]) > 30:
        for _ in range(random.randint(1, 3)):
            market["properties"].pop(random.randrange(len(market["properties"])))
    await _save_market(market)


async def _market_tick(context) -> None:
    await update_real_estate_market()


register_tick(_market_tick)


async def _check(event, action: str) -> dict:
    remaining = cd_remaining(sender_id(event), "real_estate", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试～")
    from . import base as _guards

    return await _guards.require_player(event)


def _calc_income_projection(property: dict) -> int:
    if property.get("isRented"):
        return int(property.get("rentPrice", 0) * 24 * 30)
    base_rent = property["price"] * 0.008
    renovation_bonus = property.get("renovationLevel", 0) * 0.2
    condition_bonus = (property.get("condition", 100) / 100) * 0.1
    return int(base_rent * (1 + renovation_bonus + condition_bonus))


def _maintenance_advice(property: dict) -> str:
    condition = property.get("condition", 100)
    if condition < 50:
        return "紧急：房产状况不佳，需要立即维护"
    if condition < 70:
        return "注意：房产需要维护，建议尽快装修"
    if condition < 90:
        return "提醒：房产状况良好，定期检查维护"
    return "优秀：房产状况极佳，继续保持"


def _analyze_portfolio(properties: list[dict]) -> str:
    if len(properties) <= 1:
        return "建议继续购入不同类型房产，分散投资风险"
    type_count: dict[str, int] = {}
    location_count: dict[str, int] = {}
    for p in properties:
        type_count[p["type"]] = type_count.get(p["type"], 0) + 1
        location_count[p["location"]] = location_count.get(p["location"], 0) + 1
    advice = []
    if len(type_count) < 3 and len(properties) >= 3:
        advice.append("建议购买多种类型房产分散风险")
    if len(location_count) < 3 and len(properties) >= 3:
        advice.append("建议在不同区域购买房产，降低市场风险")
    if any(p.get("renovationLevel", 0) < 2 for p in properties):
        advice.append("部分房产装修等级较低，升级装修可提高收益")
    if any(not p.get("isRented") for p in properties):
        advice.append("有未出租房产，建议出租以获取持续收益")
    if not advice:
        advice.append("您的房产组合已经非常均衡，继续保持良好的维护和管理")
    return "；".join(advice)


def _css_file() -> str:
    from ..core.renderer import BASE_HREF_DIR

    return BASE_HREF_DIR.as_uri() + "/"


@cmd(r"^#房产市场.*$", name="property_market", priority=2)
async def property_market(self, event):
    """浏览房产市场（可按类型/区域筛选）"""
    user_id = sender_id(event)
    data = await _check(event, "market")
    type_filter = event.get_message_str().replace("#房产市场", "").strip()
    market = await _load_market()
    properties = market["properties"]
    filter_message = ""
    if type_filter and type_filter in PROPERTY_TYPES:
        properties = [p for p in properties if p["type"] == type_filter]
        filter_message = f"已为您筛选{type_filter}类型的房产"
    elif type_filter and type_filter in LOCATIONS:
        properties = [p for p in properties if p["location"] == type_filter]
        filter_message = f"已为您筛选{type_filter}区域的房产"
    properties = sorted(properties, key=lambda p: p["price"])

    all_prices = [p["price"] for p in market["properties"]]
    market_analysis = {
        "totalProperties": len(market["properties"]),
        "averagePrice": sum(all_prices) // max(len(all_prices), 1),
        "priceRange": {"min": min(all_prices), "max": max(all_prices)},
        "typeDistribution": [
            {"type": t, "count": sum(1 for p in market["properties"] if p["type"] == t)}
            for t in PROPERTY_TYPES
        ],
        "locationDistribution": sorted(
            [
                {
                    "location": loc,
                    "count": sum(
                        1 for p in market["properties"] if p["location"] == loc
                    ),
                    "avgPrice": sum(
                        p["price"] for p in market["properties"] if p["location"] == loc
                    )
                    // max(
                        sum(1 for p in market["properties"] if p["location"] == loc), 1
                    ),
                }
                for loc in LOCATIONS
            ],
            key=lambda x: x["avgPrice"],
        ),
    }
    path = await renderer.render_image(
        "real_estate_market",
        {
            "cssFile": _css_file(),
            "marketData": market,
            "properties": properties,
            "hasProperties": bool(properties),
            "userMoney": data.get("money"),
            "marketAnalysis": market_analysis,
            "filterMessage": filter_message,
        },
    )
    yield event.image_result(path)
    set_cd(user_id, "real_estate", "market")
    if filter_message:
        yield filter_message
    else:
        cheapest_location = market_analysis["locationDistribution"][0]
        hottest_type = sorted(
            market_analysis["typeDistribution"],
            key=lambda x: -x["count"],
        )[0]
        yield (
            f"【房产市场信息】\n当前市场共有{market_analysis['totalProperties']}处房产\n"
            f"平均价格: {market_analysis['averagePrice']}元\n"
            f"价格区间: {market_analysis['priceRange']['min']}-"
            f"{market_analysis['priceRange']['max']}元\n\n"
            "【市场分析】\n"
            f"1. {cheapest_location['location']}区域均价最低，"
            f"约{cheapest_location['avgPrice']}元，性价比较高\n"
            f"2. 市场热门房产类型: {hottest_type['type']}\n"
            f"3. 您当前资金: {data.get('money')}元\n\n"
            "【使用提示】\n"
            "- 输入 #房产市场+类型 可筛选特定类型(如:#房产市场公寓)\n"
            "- 输入 #房产市场+区域 可筛选特定区域(如:#房产市场市中心)\n"
            "- 使用 #购买房产+ID 购买您心仪的房产"
        )


@cmd(r"^#购买房产.*$", name="property_buy", priority=7)
async def property_buy(self, event):
    """购买房产：#购买房产 [ID]"""
    user_id = sender_id(event)
    data = await _check(event, "buy")
    property_id = event.get_message_str().replace("#购买房产", "").strip()
    market = await _load_market()
    prop = next((p for p in market["properties"] if p["id"] == property_id), None)
    if prop is None:
        yield "未找到该房产信息！"
        return
    if int(data.get("money", 0)) < prop["price"]:
        yield "你的资金不足以购买该房产！"
        return
    data["money"] = int(data.get("money", 0)) - prop["price"]
    data.setdefault("properties", []).append(
        {
            **prop,
            "purchaseDate": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "condition": 100,
            "renovationLevel": 0,
            "isRented": False,
            "tenant": None,
        },
    )
    market["properties"] = [p for p in market["properties"] if p["id"] != property_id]
    await _save_market(market)
    await save_user(user_id, data)
    set_cd(user_id, "real_estate", "buy")
    yield (
        f"恭喜你成功购买了{prop['name']}！\n"
        "【购买房产攻略】\n"
        "1. 购买前检查：\n"
        "   - 确认房产位置和价格\n"
        "   - 检查自己的资金是否充足\n"
        "   - 考虑房产的升值空间\n"
        "2. 购买后建议：\n"
        "   - 及时进行装修提升价值\n"
        "   - 考虑出租获取收益\n"
        "   - 定期维护保持房产状态\n"
        "3. 注意事项：\n"
        "   - 房产价格会随市场波动\n"
        "   - 不同区域升值空间不同\n"
        "   - 装修和维护需要额外投入"
    )


@cmd(r"^#出售房产.*$", name="property_sell", priority=7)
async def property_sell(self, event):
    """出售房产：#出售房产 [ID]"""
    user_id = sender_id(event)
    data = await _check(event, "sell")
    properties = data.get("properties") or []
    if not properties:
        yield "你还没有任何房产！"
        return
    property_id = event.get_message_str().replace("#出售房产", "").strip()
    prop = next((p for p in properties if p["id"] == property_id), None)
    if prop is None:
        yield "未找到该房产信息！"
        return
    if prop.get("isRented"):
        yield "该房产正在出租中，无法出售！"
        return
    base_price = prop["price"]
    renovation_bonus = prop.get("renovationLevel", 0) * 10000
    condition_bonus = (prop.get("condition", 100) / 100) * base_price * 0.2
    sell_price = int(base_price + renovation_bonus + condition_bonus)
    data["money"] = int(data.get("money", 0)) + sell_price
    properties.remove(prop)
    market = await _load_market()
    market["properties"].append(
        {**prop, "price": int(base_price * (1 + random.random() * 0.1))},
    )
    await _save_market(market)
    await save_user(user_id, data)
    set_cd(user_id, "real_estate", "sell")
    yield (
        f"恭喜你成功出售了{prop['name']}！\n获得资金：{sell_price}元\n\n"
        "【出售房产攻略】\n"
        "1. 出售时机选择：\n"
        "   - 关注市场行情\n"
        "   - 选择升值空间大的时机\n"
        "   - 考虑装修和维护状态\n"
        "2. 价格影响因素：\n"
        "   - 房产基础价格\n"
        "   - 装修等级加成\n"
        "   - 维护状态加成\n"
        "3. 注意事项：\n"
        "   - 出租中的房产无法出售\n"
        "   - 出售前确保房产状态良好\n"
        "   - 合理评估升值空间"
    )


@cmd(r"^#(?:房产信息|我的房产)$", name="property_info", priority=2)
async def property_info(self, event):
    """查看名下房产资产概况"""
    user_id = sender_id(event)
    data = await _check(event, "info")
    properties = data.get("properties") or []
    properties.sort(key=lambda p: (not p.get("isRented"), -p["price"]))
    if properties:
        stats = {
            "totalProperties": len(properties),
            "totalValue": sum(p["price"] for p in properties),
            "totalRented": sum(1 for p in properties if p.get("isRented")),
            "totalRentIncome": sum(
                p.get("rentPrice", 0) or 0 for p in properties if p.get("isRented")
            ),
            "averageCondition": sum(p.get("condition", 100) for p in properties)
            // len(properties),
            "bestProperty": max(properties, key=lambda p: p["price"]),
            "worstCondition": min(properties, key=lambda p: p.get("condition", 100)),
        }
    else:
        stats = {
            "totalProperties": 0,
            "totalValue": 0,
            "totalRented": 0,
            "totalRentIncome": 0,
            "averageCondition": 0,
            "bestProperty": None,
            "worstCondition": None,
        }
    for prop in properties:
        prop.setdefault("features", [])
        prop["incomeProjection"] = _calc_income_projection(prop)
        prop["maintenanceAdvice"] = _maintenance_advice(prop)
    path = await renderer.render_image(
        "property_info",
        {"cssFile": _css_file(), "properties": properties, "stats": stats},
    )
    yield event.image_result(path)
    set_cd(user_id, "real_estate", "info")
    best = stats["bestProperty"]
    best_line = f"{best['name']} (价值{best['price']}元)" if best else "暂无房产"
    yield (
        f"【房产资产概况】\n您共拥有{stats['totalProperties']}处房产，"
        f"总价值{stats['totalValue']}元\n"
        f"已出租: {stats['totalRented']}处，每小时租金收入: {stats['totalRentIncome']}元\n"
        f"平均房产状况: {stats['averageCondition']}%\n\n"
        f"【最有价值房产】\n{best_line}\n\n"
        f"【投资建议】\n{_analyze_portfolio(properties)}\n\n"
        "【使用提示】\n"
        "- 输入 #出售房产+ID 可出售房产\n"
        "- 输入 #装修房产+ID+等级 可提升房产价值\n"
        "- 输入 #出租房产+ID+租金 可出租获得收益"
    )


@cmd(r"^#装修房产.*$", name="property_renovate", priority=7)
async def property_renovate(self, event):
    """装修房产：#装修房产 [ID] [等级1-5]"""
    user_id = sender_id(event)
    data = await _check(event, "renovate")
    properties = data.get("properties") or []
    if not properties:
        yield "你还没有任何房产！"
        return
    parts = event.get_message_str().replace("#装修房产", "").strip().split()
    if not parts:
        yield "格式：#装修房产 [房产ID] [装修等级1-5]"
        return
    property_id = parts[0]
    prop = next((p for p in properties if p["id"] == property_id), None)
    if prop is None:
        yield "未找到该房产信息！"
        return
    try:
        target_level = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        target_level = 0
    if target_level < 1 or target_level > 5:
        yield "装修等级必须在1-5之间！"
        return
    if prop.get("renovationLevel", 0) >= target_level:
        yield "该房产已达到或超过目标装修等级！"
        return
    total_cost = RENOVATION_COSTS[target_level]
    if int(data.get("money", 0)) < total_cost:
        yield "你的资金不足以进行装修！"
        return
    data["money"] = int(data.get("money", 0)) - total_cost
    prop["renovationLevel"] = target_level
    prop["condition"] = 100
    await save_user(user_id, data)
    set_cd(user_id, "real_estate", "renovate")
    yield (
        f"恭喜你成功将{prop['name']}装修到{target_level}级！\n花费：{total_cost}元\n\n"
        "【房产装修攻略】\n"
        "1. 装修等级说明：\n"
        "   - 1级：基础装修\n   - 2级：舒适装修\n   - 3级：豪华装修\n"
        "   - 4级：顶级装修\n   - 5级：至尊装修\n"
        "2. 装修建议：\n"
        "   - 根据房产位置选择合适等级\n"
        "   - 考虑投资回报比\n"
        "   - 注意装修成本\n"
        "3. 注意事项：\n"
        "   - 装修后房产状态会恢复\n"
        "   - 装修等级影响租金和售价\n"
        "   - 合理规划装修预算"
    )


@cmd(r"^#出租房产.*$", name="property_rent", priority=7)
async def property_rent(self, event):
    """出租房产：#出租房产 [ID] [租金]"""
    user_id = sender_id(event)
    data = await _check(event, "rent")
    properties = data.get("properties") or []
    if not properties:
        yield "你还没有任何房产！"
        return
    parts = event.get_message_str().replace("#出租房产", "").strip().split()
    if not parts:
        yield "格式：#出租房产 [房产ID] [每小时租金]"
        return
    property_id = parts[0]
    prop = next((p for p in properties if p["id"] == property_id), None)
    if prop is None:
        yield "未找到该房产信息！"
        return
    if prop.get("isRented"):
        yield "该房产已经在出租中！"
        return
    try:
        price = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        price = 0
    if price <= 0:
        yield "请输入有效的租金金额！"
        return
    base_rent = prop["price"] * 0.01
    renovation_bonus = prop.get("renovationLevel", 0) * 0.2
    condition_bonus = (prop.get("condition", 100) / 100) * 0.1
    max_rent = int(base_rent * (1 + renovation_bonus + condition_bonus))
    if price > max_rent:
        yield f"租金过高！最高可设置租金为{max_rent}元"
        return
    prop["isRented"] = True
    prop["rentPrice"] = price
    prop["tenant"] = {
        "id": f"{random.getrandbits(36):09x}"[:9],
        "name": f"租客{random.randint(0, 999)}",
        "satisfaction": 100,
        "rentStartDate": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    await save_user(user_id, data)
    set_cd(user_id, "real_estate", "rent")
    yield (
        f"恭喜你成功将{prop['name']}出租！\n租金：{price}元/小时\n"
        f"租客：{prop['tenant']['name']}\n\n"
        "【房产出租攻略】\n"
        "1. 租金设置建议：\n"
        "   - 考虑房产位置和装修\n"
        "   - 参考市场行情\n"
        "   - 注意租客满意度\n"
        "2. 出租管理：\n"
        "   - 定期检查租客满意度\n"
        "   - 及时处理租客反馈\n"
        "   - 注意房产维护\n"
        "3. 注意事项：\n"
        "   - 出租中的房产无法出售\n"
        "   - 租金过高可能影响租客满意度\n"
        "   - 定期检查房产状态"
    )
