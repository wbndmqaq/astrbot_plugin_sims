"""网吧系统 - port of ``apps/netbar/index.js`` (NetbarSystem).

The original declares 20 rules but only implements 10 (the rest crash at
runtime in Yunzai).  This port implements all 20 faithfully: creation,
upgrade, staffing, equipment, goods purchasing, VIP rooms, facility
management, staff training, in-store events and environment tuning, plus
the hourly income settlement cron.
"""

from __future__ import annotations

import random
import re
import time

from ..core import config as cfg
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.cron import register_tick
from ..core.db import load_all_users, save_user
from .base import cmd


def _netbar_cfg() -> dict:
    value = cfg.get("netbar", {})
    return value if isinstance(value, dict) else {}


async def _check(event, action: str) -> dict:
    remaining = cd_remaining(sender_id(event), "netbar", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")
    from . import base as _guards

    return await _guards.require_player(event)



def _require_netbar(data: dict) -> dict:
    netbar = data.get("netbar")
    if not netbar:
        raise CommandError("你还没有网吧！请先使用 #创建网吧")
    return netbar


def _calculate_hourly_income(netbar: dict) -> int:
    nc = _netbar_cfg()
    base = nc.get("hourlyIncome", {}).get("base", 100)
    level_bonus = (netbar.get("level", 1) - 1) * nc.get("hourlyIncome", {}).get(
        "perLevel",
        50,
    )
    computer_bonus = netbar.get("computers", 0) * nc.get("hourlyIncome", {}).get(
        "perComputer",
        10,
    )
    employee_bonus = len(netbar.get("employees") or []) * nc.get(
        "hourlyIncome",
        {},
    ).get("perEmployee", 20)
    env_multiplier = (netbar.get("environment", {}).get("comfort", 50)) / 100
    return int((base + level_bonus + computer_bonus + employee_bonus) * env_multiplier)


def _generate_employee_name() -> str:
    surnames = "张李王刘陈杨赵黄周吴"
    names = "伟芳娜敏静丽强磊洋勇军杰娟艳涛明"
    return random.choice(surnames) + random.choice(names)


async def hourly_update() -> None:
    nc = _netbar_cfg()
    for user_id, user_data in (await load_all_users()).items():
        netbar = user_data.get("netbar")
        if not netbar:
            continue
        income = _calculate_hourly_income(netbar)
        expenses = sum(
            (nc.get("employees", {}).get(emp.get("type")) or {}).get("salary", 0)
            for emp in netbar.get("employees") or []
        )
        stats = netbar.setdefault("stats", {})
        stats["totalIncome"] = stats.get("totalIncome", 0) + income
        stats["totalExpenses"] = stats.get("totalExpenses", 0) + expenses
        netbar["experience"] = netbar.get("experience", 0) + income // 100
        env = netbar.setdefault("environment", {})
        if env.get("cleanliness", 0) > 0:
            env["cleanliness"] = max(0, env["cleanliness"] - 2)
        await save_user(user_id, user_data)


async def _netbar_tick(context) -> None:
    await hourly_update()


register_tick(_netbar_tick)


# ------------------------------------------------------------- commands --
@cmd(r"^#(?:创建网吧|购买网吧)$", name="netbar_create", priority=6)
async def netbar_create(self, event):
    """创建网吧"""
    user_id = sender_id(event)
    data = await _check(event, "create")
    if data.get("netbar"):
        yield "你已经拥有一家网吧了！"
        return
    create_cost = _netbar_cfg().get("createCost", 50000)
    if int(data.get("money", 0)) < create_cost:
        yield f"创建网吧需要{create_cost}元启动资金！"
        return
    data["money"] = int(data.get("money", 0)) - create_cost
    data["netbar"] = {
        "level": 1,
        "reputation": 0,
        "experience": 0,
        "computers": 10,
        "employees": [],
        "equipment": {"computer": 10, "chair": 10, "aircon": 2, "router": 1},
        "inventory": {},
        "vipRooms": [],
        "environment": {"cleanliness": 100, "comfort": 50, "temperature": 24},
        "stats": {
            "totalIncome": 0,
            "totalExpenses": create_cost,
            "customers": 0,
        },
    }
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "create")
    netbar = data["netbar"]
    yield (
        "恭喜！你成功创建了一家网吧！\n\n"
        f"等级：{netbar['level']}\n\n"
        f"电脑数量：{netbar['computers']}台\n\n"
        f"当前资金：{data['money']}元\n\n"
        "使用 #网吧信息 查看详细信息"
    )


@cmd(r"^#网吧信息$", name="netbar_info", priority=6)
async def netbar_info(self, event):
    """查看网吧经营详情"""
    data = await _check(event, "info")
    netbar = _require_netbar(data)
    hourly_income = _calculate_hourly_income(netbar)
    upgrade_cost = (netbar["level"] ** 2) * _netbar_cfg().get(
        "upgradeCostMultiplier",
        50000,
    )
    env = netbar.get("environment", {})
    stats = netbar.get("stats", {})
    yield (
        f"{data.get('name')}的网吧\n\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"等级：{netbar['level']}级\n\n"
        f"声誉：{netbar.get('reputation', 0)}\n\n"
        f"经验：{netbar.get('experience', 0)}\n\n"
        f"电脑：{netbar.get('computers', 0)}台\n\n"
        f"员工：{len(netbar.get('employees') or [])}人\n\n"
        f"VIP包间：{len(netbar.get('vipRooms') or [])}间\n\n"
        "━━━━━━━━━━━━━━━\n\n"
        "环境指数\n\n"
        f"  清洁度：{env.get('cleanliness', 0)}%\n\n"
        f"  舒适度：{env.get('comfort', 0)}%\n\n"
        f"  温度：{env.get('temperature', 24)}°C\n\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"预计时收入：{hourly_income}元\n\n"
        f"升级费用：{upgrade_cost}元\n\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"总收入：{stats.get('totalIncome', 0)}元\n\n"
        f"总支出：{stats.get('totalExpenses', 0)}元"
    )


@cmd(r"^#网吧升级$", name="netbar_upgrade", priority=6)
async def netbar_upgrade(self, event):
    """升级网吧等级"""
    user_id = sender_id(event)
    data = await _check(event, "upgrade")
    netbar = _require_netbar(data)
    nc = _netbar_cfg()
    upgrade_cost = (netbar["level"] ** 2) * nc.get("upgradeCostMultiplier", 50000)
    required_reputation = netbar["level"] * nc.get("reputationMultiplier", 20)
    required_experience = (netbar["level"] ** 2) * nc.get(
        "experienceMultiplier",
        1000,
    )
    if int(data.get("money", 0)) < upgrade_cost:
        yield f"升级到{netbar['level'] + 1}级需要{upgrade_cost}元，你的资金不足！"
        return
    if netbar.get("reputation", 0) < required_reputation:
        yield (
            f"需要{required_reputation}点声誉，"
            f"当前只有{netbar.get('reputation', 0)}点！"
        )
        return
    if netbar.get("experience", 0) < required_experience:
        yield (
            f"需要{required_experience}点经验，"
            f"当前只有{netbar.get('experience', 0)}点！"
        )
        return
    data["money"] = int(data.get("money", 0)) - upgrade_cost
    netbar["level"] += 1
    netbar["computers"] += 5
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + upgrade_cost
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "upgrade")
    yield (
        "网吧升级成功！\n\n"
        f"当前等级：{netbar['level']}级\n\n"
        f"电脑数量：{netbar['computers']}台\n\n"
        f"剩余资金：{data['money']}元"
    )


@cmd(r"^#雇佣员工.*$", name="netbar_hire", priority=8)
async def netbar_hire(self, event):
    """雇佣员工（网吧/酒馆/影院自动分流）：#雇佣员工 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "hire")
    emp_type = event.get_message_str().replace("#雇佣员工", "").strip()
    employees_cfg = _netbar_cfg().get("employees", {})

    # 1. 检查是否为酒馆工种
    from .tavern import STAFF_TYPES as TAVERN_STAFF

    tavern_match = next(
        (
            t
            for t in TAVERN_STAFF
            if t["type"].lower() == emp_type.lower() or t["name"] == emp_type
        ),
        None,
    )
    if tavern_match is not None and emp_type not in employees_cfg:
        async for item in _delegate_tavern_hire(self, event):
            yield item
        return

    # 2. 检查是否为影院工种
    from .cinema import _config as _cinema_config

    cinema_staff_cfg = _cinema_config().get("staff") or {}
    cinema_match = next(
        (
            k
            for k, v in cinema_staff_cfg.items()
            if k.lower() == emp_type.lower() or v.get("name") == emp_type
        ),
        None,
    )
    if cinema_match is not None and emp_type not in employees_cfg:
        from .cinema import cinema_hire_staff

        async for item in cinema_hire_staff(self, event):
            yield item
        return

    # 3. 网吧自身工种
    netbar = _require_netbar(data)
    emp_cfg = employees_cfg.get(emp_type)
    if emp_cfg is None:
        types = "、".join(
            f"{k}({v.get('salary')}元/时)" for k, v in employees_cfg.items()
        )
        tavern_types = "、".join(t["name"] for t in TAVERN_STAFF)
        cinema_types = "、".join(v.get("name", k) for k, v in cinema_staff_cfg.items())
        yield (
            f"无效的员工类型！\n"
            f"网吧可选：{types}\n"
            f"酒馆可选：{tavern_types}\n"
            f"影院可选：{cinema_types}"
        )
        return
    employee = {
        "id": int(time.time() * 1000),
        "type": emp_type,
        "name": _generate_employee_name(),
        "skill": emp_cfg.get("skill"),
        "efficiency": emp_cfg.get("efficiency"),
        "salary": emp_cfg.get("salary"),
        "hiredAt": int(time.time() * 1000),
    }
    netbar.setdefault("employees", []).append(employee)
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "hire")
    yield (
        f"成功雇佣{emp_cfg.get('skill')}！\n\n"
        f"姓名：{employee['name']}\n\n"
        f"薪资：{employee['salary']}元/小时\n\n"
        f"效率：{employee['efficiency'] * 100:.0f}%"
    )


async def _delegate_tavern_hire(self, event):
    """把酒馆专属工种的雇佣委托给酒馆系统。"""
    from .tavern import (
        STAFF_TYPES,
        _apply_staff_bonuses,
        _send_image,
    )
    from .tavern import _check as _tavern_check

    user_id = sender_id(event)
    data = await _tavern_check(event, "staffHire")
    tavern = data.get("tavern")
    if not tavern:
        yield "你还没有酒馆！使用 #创建酒馆 [名称] 创建后再雇佣酒馆员工。"
        return
    emp_type = event.get_message_str().replace("#雇佣员工", "").strip()
    staff = tavern.setdefault("staff", [])
    info = next(
        (
            s
            for s in STAFF_TYPES
            if s["type"].lower() == emp_type.lower() or s["name"] == emp_type
        ),
        None,
    )
    if info is None:
        yield f"未找到员工类型: {emp_type}！"
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
    new_staff = {
        "id": f"staff_{int(time.time() * 1000):x}",
        "name": random.choice(surnames) + random.choice(given),
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
    await _send_image(
        event,
        "tavern_hire_staff",
        {"tavern": tavern, "newStaff": new_staff, "hireCost": hire_cost},
    )
    skill_lines = "\n   ".join(
        f"- {s['name']}: {s['description']}" for s in info["skills"]
    )
    yield (
        f"成功雇佣{info['name']}（酒馆员工）！\n\n"
        f"姓名：{new_staff['name']}\n\n"
        f"薪资：{new_staff['salary']}元/日\n\n"
        f"{info['description']}\n\n"
        f"相关技能：\n   {skill_lines}"
    )


@cmd(r"^#解雇员工.*$", name="netbar_fire", priority=8)
async def netbar_fire(self, event):
    """解雇员工（网吧/酒馆自动分流）：#解雇员工 [姓名]"""
    user_id = sender_id(event)
    data = await _check(event, "fire")
    netbar = data.get("netbar") or {}
    name = event.get_message_str().replace("#解雇员工", "").strip()
    employees = netbar.get("employees") or []
    target = next((emp for emp in employees if emp.get("name") == name), None)
    if target is None:
        # 1. 尝试酒馆
        tavern = data.get("tavern")
        if tavern:
            staff = tavern.get("staff") or []
            t_target = next(
                (s for s in staff if s.get("name") == name or s.get("id") == name),
                None,
            )
            if t_target is not None:
                from .tavern import _apply_staff_bonuses

                staff.remove(t_target)
                _apply_staff_bonuses(tavern)
                await save_user(user_id, data)
                set_cd(user_id, "tavern", "staffFire")
                yield f"已解雇酒馆员工：{name}"
                return
        # 2. 尝试影院
        cinema = data.get("cinema")
        if cinema:
            c_staff = cinema.get("staff") or []
            c_target = next(
                (s for s in c_staff if s.get("name") == name),
                None,
            )
            if c_target is not None:
                c_staff.remove(c_target)
                cinema["staffCost"] = max(
                    0, cinema.get("staffCost", 0) - c_target.get("salary", 0)
                )
                await save_user(user_id, data)
                set_cd(user_id, "cinema", "hire")
                yield f"已解雇影院员工：{name}"
                return
        if not netbar:
            yield "你还没有网吧！使用 #创建网吧 创建。"
            return
        yield "未找到该员工！"
        return
    employees.remove(target)
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "fire")
    yield f"已解雇员工：{name}"


@cmd(r"^#购买设备.*$", name="netbar_buy_equipment", priority=8)
async def netbar_buy_equipment(self, event):
    """购买网吧设备：#购买设备 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "buy_equip")
    netbar = _require_netbar(data)
    equipment = event.get_message_str().replace("#购买设备", "").strip()
    equip_cfg = _netbar_cfg().get("equipment", {})
    item = equip_cfg.get(equipment)
    if item is None:
        types = "、".join(f"{k}({v.get('cost')}元)" for k, v in equip_cfg.items())
        yield f"无效的设备类型！可选：{types}"
        return
    if int(data.get("money", 0)) < item["cost"]:
        yield f"资金不足！需要{item['cost']}元"
        return
    data["money"] = int(data.get("money", 0)) - item["cost"]
    netbar.setdefault("equipment", {})[equipment] = (
        netbar["equipment"].get(equipment, 0) + 1
    )
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + item["cost"]
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "buy_equip")
    yield (
        "购买成功！\n\n"
        f"设备：{equipment}\n\n"
        f"花费：{item['cost']}元\n\n"
        f"剩余资金：{data['money']}元"
    )


@cmd(r"^#维护设备.*$", name="netbar_maintain", priority=8)
async def netbar_maintain(self, event):
    """维护全部设备，恢复舒适度"""
    user_id = sender_id(event)
    data = await _check(event, "maintain")
    netbar = _require_netbar(data)
    equip_count = sum((netbar.get("equipment") or {}).values())
    if equip_count == 0:
        yield "你还没有任何设备可维护！"
        return
    cost = equip_count * 50
    if int(data.get("money", 0)) < cost:
        yield f"维护全部设备需要{cost}元，你的资金不足！"
        return
    data["money"] = int(data.get("money", 0)) - cost
    env = netbar.setdefault("environment", {})
    env["cleanliness"] = min(100, env.get("cleanliness", 0) + 10)
    env["comfort"] = min(100, env.get("comfort", 0) + 5)
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + cost
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "maintain")
    yield (
        f"设备维护完成！\n\n共维护{equip_count}件设备\n\n"
        f"花费：{cost}元\n\n清洁度+10，舒适度+5"
    )


@cmd(r"^#进货.*$", name="netbar_purchase_goods", priority=8)
async def netbar_purchase_goods(self, event):
    """进购零食饮料：#进货 [商品名] [数量]"""
    user_id = sender_id(event)
    data = await _check(event, "purchase")
    netbar = _require_netbar(data)
    params = event.get_message_str().replace("#进货", "").strip().split()
    food_items = _netbar_cfg().get("foodItems", {})
    if len(params) != 2:
        items = "、".join(
            f"{v.get('name')}({v.get('cost')}元/{v.get('unit')})"
            for v in food_items.values()
        )
        yield f"格式：#进货 [商品名] [数量]。可进货：{items}"
        return
    item_name, quantity_str = params
    try:
        quantity = int(quantity_str)
    except ValueError:
        quantity = 0
    item_key = next(
        (k for k, v in food_items.items() if v.get("name") == item_name),
        None,
    )
    if item_key is None:
        yield "无效的商品名称！"
        return
    if quantity <= 0:
        yield "数量必须为正整数！"
        return
    item = food_items[item_key]
    total_cost = item["cost"] * quantity
    if int(data.get("money", 0)) < total_cost:
        yield f"资金不足！需要{total_cost}元"
        return
    data["money"] = int(data.get("money", 0)) - total_cost
    netbar.setdefault("inventory", {})[item_key] = netbar["inventory"].get(
        item_key,
        0,
    ) + quantity * item.get("stock", 1)
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + total_cost
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "purchase")
    yield (
        "进货成功！\n\n"
        f"商品：{item['name']}\n\n"
        f"数量：{quantity * item.get('stock', 1)}{item.get('unit', '个')}\n\n"
        f"花费：{total_cost}元"
    )


@cmd(r"^#库存查询$", name="netbar_inventory", priority=6)
async def netbar_inventory(self, event):
    """查询网吧库存"""
    data = await _check(event, "inventory")
    netbar = _require_netbar(data)
    inventory = netbar.get("inventory") or {}
    if not inventory:
        yield "库存为空！使用 #进货 补充库存"
        return
    food_items = _netbar_cfg().get("foodItems", {})
    rows = []
    for key, count in inventory.items():
        item = food_items.get(key) or {}
        rows.append(f"{item.get('name', key)}: {count}{item.get('unit', '个')}")
    yield "网吧库存：\n" + "\n".join(rows)


@cmd(r"^#点餐.*$", name="netbar_order_food", priority=8)
async def netbar_order_food(self, event):
    """模拟顾客点餐，赚取餐饮收入：#点餐 [商品名] [数量]"""
    user_id = sender_id(event)
    data = await _check(event, "order")
    netbar = _require_netbar(data)
    params = event.get_message_str().replace("#点餐", "").strip().split()
    food_items = _netbar_cfg().get("foodItems", {})
    if not params:
        menu = "、".join(
            f"{v.get('name')}({v.get('price')}元)" for v in food_items.values()
        )
        yield f"格式：#点餐 [商品名] [数量]。菜单：{menu}"
        return
    item_name = params[0]
    try:
        quantity = int(params[1]) if len(params) > 1 else 1
    except ValueError:
        quantity = 0
    item_key = next(
        (k for k, v in food_items.items() if v.get("name") == item_name),
        None,
    )
    if item_key is None:
        yield "无效的商品名称！使用 #餐饮菜单 查看可售商品"
        return
    if quantity <= 0:
        yield "数量必须为正整数！"
        return
    inventory = netbar.setdefault("inventory", {})
    if inventory.get(item_key, 0) < quantity:
        yield f"库存不足！当前{item_name}库存：{inventory.get(item_key, 0)}"
        return
    item = food_items[item_key]
    revenue = item["price"] * quantity
    inventory[item_key] -= quantity
    stats = netbar.setdefault("stats", {})
    stats["totalIncome"] = stats.get("totalIncome", 0) + revenue
    stats["customers"] = stats.get("customers", 0) + quantity
    netbar["experience"] = netbar.get("experience", 0) + quantity
    data["money"] = int(data.get("money", 0)) + revenue
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "order")
    yield (
        f"顾客点餐成功！\n\n商品：{item['name']} x{quantity}\n\n"
        f"收入：{revenue}元\n\n当前资金：{data['money']}元"
    )


@cmd(r"^#餐饮菜单$", name="netbar_menu", priority=6)
async def netbar_menu(self, event):
    """查看网吧餐饮菜单"""
    data = await _check(event, "menu")
    _require_netbar(data)
    food_items = _netbar_cfg().get("foodItems", {})
    rows = [
        f"{v.get('name')}: 售价{v.get('price')}元 (成本{v.get('cost')}元)"
        for v in food_items.values()
    ]
    yield "网吧餐饮菜单\n\n━━━━━━━━━━━━━━━\n\n" + "\n\n".join(rows)


@cmd(r"^#设置价格.*$", name="netbar_set_price", priority=8)
async def netbar_set_price(self, event):
    """自定义商品售价：#设置价格 [商品名] [价格]"""
    user_id = sender_id(event)
    data = await _check(event, "set_price")
    netbar = _require_netbar(data)
    params = event.get_message_str().replace("#设置价格", "").strip().split()
    if len(params) != 2:
        yield "格式：#设置价格 [商品名] [价格]"
        return
    item_name, price_str = params
    food_items = _netbar_cfg().get("foodItems", {})
    item_key = next(
        (k for k, v in food_items.items() if v.get("name") == item_name),
        None,
    )
    if item_key is None:
        yield "无效的商品名称！"
        return
    try:
        price = int(price_str)
    except ValueError:
        price = 0
    if price <= 0:
        yield "价格必须为正整数！"
        return
    cost = food_items[item_key].get("cost", 0)
    if price < cost:
        yield f"售价不能低于成本价{cost}元！"
        return
    prices = netbar.setdefault("customPrices", {})
    prices[item_key] = price
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "set_price")
    yield f"{item_name}的售价已设置为{price}元"


@cmd(r"^#开设包间.*$", name="netbar_vip_setup", priority=8)
async def netbar_vip_setup(self, event):
    """开设VIP包间：#开设包间 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "vip_setup")
    netbar = _require_netbar(data)
    room_type = event.get_message_str().replace("#开设包间", "").strip()
    rooms_cfg = _netbar_cfg().get("vipRooms", {})
    room = rooms_cfg.get(room_type)
    if room is None:
        types = "、".join(
            f"{k}({v.get('cost')}元, {v.get('computers')}台电脑)"
            for k, v in rooms_cfg.items()
        )
        yield f"格式：#开设包间 [类型]。可选：{types}"
        return
    if int(data.get("money", 0)) < room["cost"]:
        yield f"资金不足！需要{room['cost']}元"
        return
    data["money"] = int(data.get("money", 0)) - room["cost"]
    netbar.setdefault("vipRooms", []).append(
        {
            "type": room_type,
            "name": room.get("name"),
            "computers": room.get("computers"),
            "status": "available",
            "bookings": [],
        },
    )
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + room["cost"]
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "vip_setup")
    yield (
        f"成功开设{room.get('name')}！\n\n"
        f"电脑数量：{room.get('computers')}台\n\n"
        f"花费：{room.get('cost')}元"
    )


@cmd(r"^#包间预订.*$", name="netbar_vip_book", priority=8)
async def netbar_vip_book(self, event):
    """预订VIP包间：#包间预订 [包间序号] [小时]"""
    user_id = sender_id(event)
    data = await _check(event, "vip_book")
    netbar = _require_netbar(data)
    params = event.get_message_str().replace("#包间预订", "").strip().split()
    if not params:
        yield "格式：#包间预订 [包间序号] [小时]"
        return
    try:
        index = int(params[0]) - 1
    except ValueError:
        index = -1
    rooms = netbar.get("vipRooms") or []
    if index < 0 or index >= len(rooms):
        yield f"无效的包间序号！当前共有{len(rooms)}间包间。"
        return
    room = rooms[index]
    if room.get("status") != "available":
        yield f"{room.get('name')}当前不可预订（{room.get('status')}）！"
        return
    try:
        hours = int(params[1]) if len(params) > 1 else 1
    except ValueError:
        hours = 0
    if hours <= 0:
        yield "预订时长必须为正整数小时！"
        return
    hourly_rate = 50 * (index + 1)
    revenue = hourly_rate * hours
    room["status"] = "booked"
    room.setdefault("bookings", []).append(
        {"hours": hours, "revenue": revenue, "time": time.strftime("%Y-%m-%d %H:%M")},
    )
    stats = netbar.setdefault("stats", {})
    stats["totalIncome"] = stats.get("totalIncome", 0) + revenue
    netbar["experience"] = netbar.get("experience", 0) + hours * 5
    data["money"] = int(data.get("money", 0)) + revenue
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "vip_book")
    yield (
        f"{room.get('name')}预订成功！\n\n"
        f"时长：{hours}小时\n\n"
        f"包间收入：{revenue}元\n\n"
        "使用 #包间服务 提供服务，#包间状态 查看状态"
    )


@cmd(r"^#包间状态$", name="netbar_vip_status", priority=6)
async def netbar_vip_status(self, event):
    """查看全部包间状态"""
    data = await _check(event, "vip_status")
    netbar = _require_netbar(data)
    rooms = netbar.get("vipRooms") or []
    if not rooms:
        yield "你还没有开设任何包间！使用 #开设包间 [类型] 开设。"
        return
    status_map = {"available": "空闲", "booked": "已预订", "serving": "服务中"}
    rows = []
    for i, room in enumerate(rooms):
        rows.append(
            f"{i + 1}.{room.get('name')} [{status_map.get(room.get('status'), room.get('status'))}]"
            f" {room.get('computers')}台电脑",
        )
    yield "VIP包间状态\n\n" + "\n\n".join(rows)


@cmd(r"^#包间服务.*$", name="netbar_vip_service", priority=8)
async def netbar_vip_service(self, event):
    """为预订中的包间提供服务：#包间服务 [包间序号]"""
    user_id = sender_id(event)
    data = await _check(event, "vip_service")
    netbar = _require_netbar(data)
    raw = event.get_message_str().replace("#包间服务", "").strip()
    try:
        index = int(raw) - 1 if raw else -1
    except ValueError:
        index = -1
    rooms = netbar.get("vipRooms") or []
    if index < 0 or index >= len(rooms):
        yield f"格式：#包间服务 [包间序号]，范围 1-{len(rooms)}"
        return
    room = rooms[index]
    if room.get("status") == "available":
        yield f"{room.get('name')}当前空闲，无需服务。"
        return
    revenue = 100 * max(1, room.get("computers", 4) // 2)
    room["status"] = "available"
    stats = netbar.setdefault("stats", {})
    stats["totalIncome"] = stats.get("totalIncome", 0) + revenue
    stats["customers"] = stats.get("customers", 0) + 1
    netbar["reputation"] = netbar.get("reputation", 0) + 1
    data["money"] = int(data.get("money", 0)) + revenue
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "vip_service")
    yield (
        f"为{room.get('name')}提供了结账服务！\n\n"
        f"服务收入：{revenue}元\n\n声誉+1\n\n包间已恢复为空闲状态"
    )


@cmd(r"^#设施(添加|升级|维护).*$", name="netbar_facilities", priority=8)
async def netbar_facilities(self, event):
    """设施管理：#设施添加/升级/维护 [类型]"""
    user_id = sender_id(event)
    data = await _check(event, "facility_mgr")
    netbar = _require_netbar(data)
    raw = event.get_message_str()
    match = re.match(r"^#设施(添加|升级|维护)\s*(.*)$", raw)
    action = match.group(1) if match else "添加"
    target = (match.group(2) if match else "").strip()
    env = netbar.setdefault("environment", {})
    if action == "维护":
        cost = 500
        if int(data.get("money", 0)) < cost:
            yield f"设施维护需要{cost}元，你的资金不足！"
            return
        data["money"] = int(data.get("money", 0)) - cost
        env["comfort"] = min(100, env.get("comfort", 0) + 8)
        env["cleanliness"] = min(100, env.get("cleanliness", 0) + 5)
        netbar.setdefault("stats", {})["totalExpenses"] = (
            netbar["stats"].get("totalExpenses", 0) + cost
        )
        await save_user(user_id, data)
        set_cd(user_id, "netbar", "facility_mgr")
        yield f"设施维护完成！花费{cost}元，舒适度+8，清洁度+5"
        return
    facilities = netbar.setdefault("facilities", {})
    if not target:
        owned = "、".join(f"{k} Lv.{v}" for k, v in facilities.items()) or "无"
        yield (
            "格式：#设施添加 [类型] 或 #设施升级 [类型]。\n"
            "可选设施：电竞椅、机械键盘、曲面显示器、环绕音响\n"
            f"当前设施：{owned}"
        )
        return
    if action == "添加":
        if target in facilities:
            yield f"你已拥有{target}！可使用 #设施升级 {target} 提升等级。"
            return
        cost = 3000
        if int(data.get("money", 0)) < cost:
            yield f"添加{target}需要{cost}元，你的资金不足！"
            return
        data["money"] = int(data.get("money", 0)) - cost
        facilities[target] = 1
        env["comfort"] = min(100, env.get("comfort", 0) + 5)
        netbar.setdefault("stats", {})["totalExpenses"] = (
            netbar["stats"].get("totalExpenses", 0) + cost
        )
        await save_user(user_id, data)
        set_cd(user_id, "netbar", "facility_mgr")
        yield f"成功添加{target}！花费{cost}元，舒适度+5"
    else:
        if target not in facilities:
            yield f"你还没有{target}！请先使用 #设施添加 {target}。"
            return
        level = facilities[target]
        cost = 3000 * (level + 1)
        if int(data.get("money", 0)) < cost:
            yield f"升级{target}到{level + 1}级需要{cost}元，你的资金不足！"
            return
        data["money"] = int(data.get("money", 0)) - cost
        facilities[target] = level + 1
        env["comfort"] = min(100, env.get("comfort", 0) + 3)
        netbar.setdefault("stats", {})["totalExpenses"] = (
            netbar["stats"].get("totalExpenses", 0) + cost
        )
        await save_user(user_id, data)
        set_cd(user_id, "netbar", "facility_mgr")
        yield (
            f"{target}升级成功！\n当前等级：Lv.{level + 1}\n花费：{cost}元，舒适度+3"
        )


@cmd(r"^#员工培训.*$", name="netbar_train_employee", priority=8)
async def netbar_train_employee(self, event):
    """培训员工提升效率：#员工培训 [姓名]"""
    user_id = sender_id(event)
    data = await _check(event, "train_emp")
    netbar = _require_netbar(data)
    name = event.get_message_str().replace("#员工培训", "").strip()
    employees = netbar.get("employees") or []
    employee = next((emp for emp in employees if emp.get("name") == name), None)
    if employee is None:
        yield "未找到该员工！使用 #网吧信息 查看员工数量。"
        return
    cost = 500
    if int(data.get("money", 0)) < cost:
        yield f"培训员工需要{cost}元，你的资金不足！"
        return
    data["money"] = int(data.get("money", 0)) - cost
    employee["efficiency"] = round(min(2.0, employee.get("efficiency", 1) + 0.1), 2)
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + cost
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "train_emp")
    yield (
        f"培训完成！{name}的效率提升至{employee['efficiency'] * 100:.0f}%\n"
        f"花费：{cost}元"
    )


@cmd(r"^#举办活动.*$", name="netbar_event", priority=8)
async def netbar_event(self, event):
    """举办店内活动：#举办活动 [活动名称]"""
    user_id = sender_id(event)
    data = await _check(event, "event")
    netbar = _require_netbar(data)
    event_name = event.get_message_str().replace("#举办活动", "").strip()
    if not event_name:
        yield "请输入活动名称！格式：#举办活动 [活动名称]"
        return
    cost = 2000
    if int(data.get("money", 0)) < cost:
        yield f"举办活动需要{cost}元经费，你的资金不足！"
        return
    data["money"] = int(data.get("money", 0)) - cost
    reputation_gain = random.randint(3, 10)
    customers = random.randint(10, 30)
    revenue = customers * random.randint(20, 50)
    netbar["reputation"] = netbar.get("reputation", 0) + reputation_gain
    stats = netbar.setdefault("stats", {})
    stats["totalIncome"] = stats.get("totalIncome", 0) + revenue
    stats["customers"] = stats.get("customers", 0) + customers
    stats["totalExpenses"] = stats.get("totalExpenses", 0) + cost
    netbar["experience"] = netbar.get("experience", 0) + 20
    data["money"] = int(data.get("money", 0)) + revenue
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "event")
    yield (
        f"活动[{event_name}]举办成功！\n\n"
        f"参与顾客：{customers}人\n\n"
        f"活动收入：{revenue}元\n\n"
        f"声誉+{reputation_gain}\n\n"
        f"净利润：{revenue - cost}元"
    )


@cmd(r"^#调整环境.*$", name="netbar_adjust_env", priority=8)
async def netbar_adjust_env(self, event):
    """调整网吧环境：#调整环境 [清洁/温度/舒适]"""
    user_id = sender_id(event)
    data = await _check(event, "env")
    netbar = _require_netbar(data)
    target = event.get_message_str().replace("#调整环境", "").strip()
    env = netbar.setdefault("environment", {})
    cost = 300
    if int(data.get("money", 0)) < cost:
        yield f"调整环境需要{cost}元，你的资金不足！"
        return
    if target in {"清洁", "清洁度"}:
        env["cleanliness"] = min(100, env.get("cleanliness", 0) + 20)
        detail = f"清洁度提升至{env['cleanliness']}%"
    elif target == "温度":
        env["temperature"] = 24
        detail = "温度已调整为24°C"
    elif target in {"舒适", "舒适度"}:
        env["comfort"] = min(100, env.get("comfort", 0) + 10)
        detail = f"舒适度提升至{env['comfort']}%"
    else:
        yield "格式：#调整环境 [清洁/温度/舒适]"
        return
    data["money"] = int(data.get("money", 0)) - cost
    netbar.setdefault("stats", {})["totalExpenses"] = (
        netbar["stats"].get("totalExpenses", 0) + cost
    )
    await save_user(user_id, data)
    set_cd(user_id, "netbar", "env")
    yield f"环境调整完成！{detail}\n花费：{cost}元"
