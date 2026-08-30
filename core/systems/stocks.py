"""模拟股市体系：股票行情演化、买入卖出与持仓盈亏。"""

from __future__ import annotations

import random
import time
from typing import Any

from .. import gamedata
from ..cron import register_tick
from ..db import db

STOCK_KV = "stock_market"


async def load_stock_market() -> dict[str, Any]:
    data = await db.read_kv(STOCK_KV, None)
    if isinstance(data, dict) and isinstance(data.get("stocks"), list):
        return data
    seeded = gamedata.load_data("stockMarket.json")
    if isinstance(seeded, dict) and isinstance(seeded.get("stocks"), list):
        seeded.setdefault("lastUpdated", time.time())
        await save_stock_market(seeded)
        return seeded
    market = {
        "stocks": [
            {"id": "AAPL", "name": "苹果科技", "price": 150.0, "change": 0.0, "history": [150.0]},
            {"id": "MSFT", "name": "微积分软件", "price": 280.0, "change": 0.0, "history": [280.0]},
            {"id": "GOOG", "name": "谷歌探索", "price": 120.0, "change": 0.0, "history": [120.0]},
            {"id": "AMZN", "name": "亚马逊网络", "price": 130.0, "change": 0.0, "history": [130.0]},
            {"id": "TSLA", "name": "特斯拉动能", "price": 200.0, "change": 0.0, "history": [200.0]},
        ],
        "lastUpdated": time.time(),
    }
    await save_stock_market(market)
    return market


async def save_stock_market(data: dict) -> None:
    await db.write_kv(STOCK_KV, data)


async def update_stock_prices() -> None:
    market = await load_stock_market()
    for stock in market.get("stocks", []):
        old_price = float(stock.get("price", 100))
        fluctuation = (random.random() * 0.2) - 0.095  # -9.5% ~ +10.5%
        new_price = max(1.0, round(old_price * (1 + fluctuation), 2))
        change = round(((new_price - old_price) / old_price) * 100, 2)
        stock["price"] = new_price
        stock["change"] = change
        history = stock.setdefault("history", [])
        history.append(new_price)
        if len(history) > 20:
            stock["history"] = history[-20:]
    market["lastUpdated"] = time.time()
    await save_stock_market(market)


async def _stocks_tick(context: Any) -> None:
    await update_stock_prices()


register_tick(_stocks_tick)
