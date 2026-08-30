"""酒馆经营体系：调酒、物资采购、雇佣、随机营业事件。"""

from __future__ import annotations

import random
import time
from typing import Any

from .. import gamedata
from ..cron import register_tick
from ..db import db

TAVERN_KV = "tavern_market"


async def load_tavern_market() -> dict[str, Any]:
    data = await db.read_kv(TAVERN_KV, None)
    if isinstance(data, dict) and isinstance(data.get("supplies"), list):
        return data
    seeded = gamedata.load_data("tavern/tavern_market.json")
    if isinstance(seeded, dict) and isinstance(seeded.get("supplies"), list):
        seeded.setdefault("lastUpdated", time.time())
        await save_tavern_market(seeded)
        return seeded
    market = {"supplies": [], "lastUpdated": time.time()}
    await save_tavern_market(market)
    return market


async def save_tavern_market(data: dict) -> None:
    await db.write_kv(TAVERN_KV, data)


async def update_tavern_market() -> None:
    market = await load_tavern_market()
    for supply in market.get("supplies", []):
        base_price = supply.get("basePrice", supply.get("price", 100))
        volatility = supply.get("volatility", 0.15)
        fluctuation = (random.random() * 2 - 1) * volatility
        new_price = max(int(base_price * 0.5), int(base_price * (1 + fluctuation)))
        supply["price"] = new_price
        # 补货
        supply["stock"] = min(200, supply.get("stock", 0) + random.randint(5, 15))
    market["lastUpdated"] = time.time()
    await save_tavern_market(market)


async def _tavern_tick(context: Any) -> None:
    await update_tavern_market()


register_tick(_tavern_tick)
