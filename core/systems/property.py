"""房产市场体系：买卖、装修、出租与行情演化。"""

from __future__ import annotations

import random
import time
from typing import Any

from ..cron import register_tick
from ..db import db

MARKET_KV = "real_estate_market"
PROPERTY_TYPES = ["单身公寓", "普通住宅", "豪华公寓", "独栋别墅", "商业商铺", "写字楼"]
LOCATIONS = ["市中心", "商业区", "大学城", "高新区", "郊区", "海滨区"]


def generate_new_property() -> dict[str, Any]:
    ptype = random.choice(PROPERTY_TYPES)
    location = random.choice(LOCATIONS)
    base_prices = {
        "单身公寓": 200000, "普通住宅": 500000, "豪华公寓": 1200000,
        "独栋别墅": 3500000, "商业商铺": 1800000, "写字楼": 5000000,
    }
    price = int(base_prices[ptype] * (random.random() * 0.4 + 0.8))
    pid = f"PROP_{int(time.time() * 1000) % 1000000}_{random.randint(10, 99)}"
    return {
        "id": pid,
        "name": f"{location}{ptype}",
        "type": ptype,
        "location": location,
        "price": price,
        "renovationLevel": 0,
        "condition": random.randint(85, 100),
        "isRented": False,
        "rentPrice": 0,
        "features": [],
    }


async def load_real_estate_market() -> dict[str, Any]:
    data = await db.read_kv(MARKET_KV, None)
    if isinstance(data, dict) and isinstance(data.get("properties"), list):
        return data
    initial = {"properties": [generate_new_property() for _ in range(12)], "lastUpdated": time.time()}
    await save_real_estate_market(initial)
    return initial


async def save_real_estate_market(data: dict) -> None:
    await db.write_kv(MARKET_KV, data)


async def update_real_estate_market() -> None:
    market = await load_real_estate_market()
    for prop in market.get("properties", []):
        change = (random.random() * 0.08) - 0.035
        prop["price"] = max(10000, int(prop["price"] * (1 + change)))
    if len(market["properties"]) < 20:
        market["properties"].append(generate_new_property())
    elif len(market["properties"]) > 30:
        market["properties"].pop(0)
    market["lastUpdated"] = time.time()
    await save_real_estate_market(market)


async def _property_tick(context: Any) -> None:
    await update_real_estate_market()


register_tick(_property_tick)
