"""电竞网吧经营体系：设备升级、小吃进货、包间赛事与收益结算。"""

from __future__ import annotations


def calculate_hourly_income(netbar: dict) -> int:
    computers = netbar.get("computers", 10)
    price_per_hour = netbar.get("pricePerHour", 5)
    reputation = netbar.get("reputation", 50)
    occupancy_rate = min(1.0, (reputation / 100.0) * 0.8 + 0.2)
    active_pcs = int(computers * occupancy_rate)
    pc_income = active_pcs * price_per_hour

    # 零食利润
    snacks_income = int(pc_income * 0.3)
    return pc_income + snacks_income
