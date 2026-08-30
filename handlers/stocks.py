"""模拟炒股 - port of ``apps/股票交易.js``.

Market prices random-walk every 5 minutes (cron); holdings track weighted
average buy price and profit/loss.
"""

from __future__ import annotations

import random
import time
from typing import Any

from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import check_user, get_store, save_user
from ..core.renderer import renderer
from .base import cmd

STOCK_KV = "stock_market"

GUIDE = """# 模拟炒股攻略

## 基本操作
1. 查看股市：发送 #股市
2. 买入股票：发送 #买入股票 股票代码 数量
3. 卖出股票：发送 #卖出股票 股票代码 数量
4. 查看持仓：发送 #我的股票

## 投资技巧
1. 分散投资：不要把所有资金都投入一只股票
2. 观察走势：股票价格每5分钟更新一次
3. 合理止盈止损：设定好自己的盈亏目标
4. 关注股票波动性：不同股票的波动率不同

## 股票列表
- AAPL：苹果科技
- GOOG：谷歌科技
- TSLA：特斯拉
- BABA：阿里巴巴
- TENC：腾讯控股

## 注意事项
1. 股市有风险，投资需谨慎
2. 合理控制投资规模
3. 不要追涨杀跌
4. 保持良好的心态"""

TRADE_GUIDE = """# 交易操作提示

1. 可以使用 #我的股票 查看当前持仓
2. 使用 #股市 查看最新行情
3. 合理设置止盈止损点
4. 建议分批建仓和清仓
5. 注意观察市场走势"""


def _initial_stocks() -> list[dict]:
    stocks = game_data._load("stockMarket.json")
    if isinstance(stocks, dict) and stocks.get("stocks"):
        return stocks["stocks"]
    return [
        {"id": "AAPL", "name": "苹果科技", "price": 150, "volatility": 0.05},
        {"id": "GOOG", "name": "谷歌科技", "price": 2800, "volatility": 0.04},
        {"id": "TSLA", "name": "特斯拉", "price": 900, "volatility": 0.08},
        {"id": "BABA", "name": "阿里巴巴", "price": 120, "volatility": 0.06},
        {"id": "TENC", "name": "腾讯控股", "price": 400, "volatility": 0.05},
    ]


async def _load_market() -> dict[str, Any]:
    data = await get_store().read_kv(STOCK_KV, None)
    if isinstance(data, dict) and data.get("stocks"):
        return data
    market = {"stocks": _initial_stocks(), "lastUpdate": int(time.time() * 1000)}
    await _save_market(market)
    return market


async def _save_market(data: dict) -> None:
    await get_store().write_kv(STOCK_KV, data)


async def update_stock_prices() -> None:
    market = await _load_market()
    for stock in market["stocks"]:
        change = (random.random() - 0.5) * 2 * stock.get("volatility", 0.05)
        stock["price"] = max(1.0, round(stock["price"] * (1 + change), 2))
    market["lastUpdate"] = int(time.time() * 1000)
    await _save_market(market)


async def _stock_tick(context) -> None:
    await update_stock_prices()


register_tick(_stock_tick)


def _css_file() -> str:
    from ..core.renderer import BASE_HREF_DIR

    return BASE_HREF_DIR.as_uri() + "/"


@cmd(r"^#股市$", name="stock_market_view", priority=4)
async def stock_market_view(self, event):
    """查看股市行情"""
    remaining = cd_remaining(sender_id(event), "stock", "view")
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试～")
    market = await _load_market()
    set_cd(sender_id(event), "stock", "view")
    path = await renderer.render_image(
        "stock_market",
        {"cssFile": _css_file(), "stocks": market["stocks"]},
    )
    yield event.image_result(path)


def _parse_trade(event, verb: str) -> tuple[str, int] | None:
    import re

    match = re.match(rf"^#{verb}\s*(\w+)\s*(\d+)$", event.get_message_str().strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


@cmd(r"^#买入股票.*$", name="stock_buy", priority=4)
async def stock_buy(self, event):
    """买入股票：#买入股票 代码 数量"""
    user_id = sender_id(event)
    remaining = cd_remaining(user_id, "stock", "trade")
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试～")
    user = await check_user(user_id)
    if user is None:
        yield "请先创建模拟人生角色！"
        return
    parsed = _parse_trade(event, "买入股票")
    if parsed is None:
        yield "格式错误！正确格式：#买入股票 股票代码 数量"
        return
    stock_id, amount = parsed
    if amount <= 0:
        yield "买入数量必须大于 0！"
        return
    market = await _load_market()
    stock = next((s for s in market["stocks"] if s["id"] == stock_id), None)
    if stock is None:
        yield "未找到该股票！"
        return
    total_cost = int(stock["price"] * amount)
    if int(user.get("money", 0)) < total_cost:
        yield "余额不足！"
        return
    user["money"] = int(user.get("money", 0)) - total_cost
    holdings = user.setdefault("stocks", [])
    existing = next((s for s in holdings if s["id"] == stock_id), None)
    if existing:
        total_amount = existing["amount"] + amount
        existing["buyPrice"] = round(
            (existing["buyPrice"] * existing["amount"] + stock["price"] * amount)
            / total_amount,
            2,
        )
        existing["amount"] = total_amount
    else:
        holdings.append(
            {
                "id": stock_id,
                "name": stock["name"],
                "amount": amount,
                "buyPrice": stock["price"],
            },
        )
    await save_user(user_id, user)
    set_cd(user_id, "stock", "trade")
    yield f"成功买入{stock['name']} {amount}股，共花费{total_cost}元！\n\n{TRADE_GUIDE}"


@cmd(r"^#卖出股票.*$", name="stock_sell", priority=4)
async def stock_sell(self, event):
    """卖出股票：#卖出股票 代码 数量"""
    user_id = sender_id(event)
    remaining = cd_remaining(user_id, "stock", "trade")
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试～")
    user = await check_user(user_id)
    if user is None or not user.get("stocks"):
        yield "你没有任何股票！"
        return
    parsed = _parse_trade(event, "卖出股票")
    if parsed is None:
        yield "格式错误！正确格式：#卖出股票 股票代码 数量"
        return
    stock_id, amount = parsed
    if amount <= 0:
        yield "卖出数量必须大于 0！"
        return
    market = await _load_market()
    stock = next((s for s in market["stocks"] if s["id"] == stock_id), None)
    if stock is None:
        yield "未找到该股票！"
        return
    holding = next((s for s in user["stocks"] if s["id"] == stock_id), None)
    if holding is None or holding["amount"] < amount:
        yield "你没有足够的股票！"
        return
    total_earning = int(stock["price"] * amount)
    profit = total_earning - int(holding["buyPrice"] * amount)
    user["money"] = int(user.get("money", 0)) + total_earning
    holding["amount"] -= amount
    if holding["amount"] == 0:
        user["stocks"] = [s for s in user["stocks"] if s["id"] != stock_id]
    await save_user(user_id, user)
    set_cd(user_id, "stock", "trade")
    sign = "+" if profit > 0 else ""
    yield (
        f"成功卖出{stock['name']} {amount}股，获得{total_earning}元！\n\n"
        f"盈亏：{sign}{profit}元\n\n{TRADE_GUIDE}"
    )


@cmd(r"^#我的股票$", name="stock_my", priority=4)
async def stock_my(self, event):
    """查看股票持仓与盈亏"""
    user_id = sender_id(event)
    remaining = cd_remaining(user_id, "stock", "view")
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试～")
    user = await check_user(user_id)
    if user is None or not user.get("stocks"):
        yield "你还没有购买任何股票！"
        return
    user_stocks = []
    market = await _load_market()
    for holding in user["stocks"]:
        current = next(
            (s for s in market["stocks"] if s["id"] == holding["id"]),
            None,
        )
        if current is None:
            continue
        current_value = int(current["price"] * holding["amount"])
        profit = current_value - int(holding["buyPrice"] * holding["amount"])
        user_stocks.append(
            {
                **holding,
                "currentPrice": current["price"],
                "currentValue": current_value,
                "profit": profit,
            },
        )
    set_cd(user_id, "stock", "view")
    path = await renderer.render_image(
        "my_stocks",
        {"cssFile": _css_file(), "userStocks": user_stocks},
    )
    yield event.image_result(path)


@cmd(r"^#股票攻略$", name="stock_guide", priority=4)
async def stock_guide(self, event):
    """查看模拟炒股攻略"""
    yield GUIDE
