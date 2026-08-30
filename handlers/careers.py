"""统一职业系统 - port of ``apps/careers/index.js`` (CareerSystem).

24 commands: career selection/work/promotion/skills/resign, per-career
actions, cross-player collaboration (invites/pairs/hall/leave) and
cross-career chain quests (view/complete/delegate/takeover), plus the
daily work-count reset cron.
"""

from __future__ import annotations

import random
import time
from typing import Any

from ..core import config as cfg
from ..core import gamedata as game_data
from ..core.context import CommandError, cd_remaining, sender_id, set_cd
from ..core.db import check_user, get_store, load_all_users, save_user
from .base import cmd

COLLAB_KV = "careers_collab"


# --------------------------------------------------------------- collab --
def _default_collab() -> dict[str, Any]:
    return {
        "seq": 0,
        "invites": [],
        "pairs": {},
        "chains": {},
        "takeovers": [],
        "stats": {},
    }


async def _load_collab() -> dict[str, Any]:
    data = await get_store().read_kv(COLLAB_KV, None)
    merged = _default_collab()
    if isinstance(data, dict):
        merged.update(data)
    return merged


async def _save_collab(data: dict[str, Any]) -> None:
    await get_store().write_kv(COLLAB_KV, data)


def _clean_expired(data: dict[str, Any]) -> None:
    now = time.time() * 1000
    data["invites"] = [i for i in data.get("invites", []) if i.get("expire", 0) > now]
    data["takeovers"] = [
        t for t in data.get("takeovers", []) if t.get("expire", 0) > now
    ]
    for uid in list(data.get("pairs", {}).keys()):
        if data["pairs"][uid].get("until", 0) <= now:
            del data["pairs"][uid]


def _find_synergy(career_a: str, career_b: str) -> dict:
    for synergy in cfg.get("careers.synergies", []) or []:
        careers = synergy.get("careers") or []
        if career_a in careers and career_b in careers and career_a != career_b:
            return synergy
    return {
        "name": "友好协作",
        "bonus": cfg.get("careers.collab.genericBonus", 0.05),
        "desc": "跨职业通用协作加成",
    }


def _career_name(career_id: str) -> str:
    career = game_data.get_career(career_id)
    return career.get("name", career_id) if career else career_id


def _bump_stat(data: dict, user_id: str, key: str) -> None:
    stats = data.setdefault("stats", {})
    entry = stats.setdefault(
        user_id, {"collabCount": 0, "chainDone": 0, "takeoverDone": 0}
    )
    entry[key] = entry.get(key, 0) + 1


def _chain_state(data: dict, user_id: str) -> dict:
    chains = data.setdefault("chains", {})
    if user_id not in chains:
        chains[user_id] = {"active": "", "progress": {}}
    return chains[user_id]


def _reward_brief(reward: dict) -> str:
    parts = []
    if reward.get("money"):
        parts.append(f"金币x{reward['money']}")
    if reward.get("exp"):
        parts.append(f"职业经验x{reward['exp']}")
    for item in reward.get("items") or []:
        parts.append(f"{item.get('name')}x{item.get('count', 1)}")
    return " ".join(parts)


async def _grant_chain_reward(user_id: str, reward: dict) -> bool:
    user_data = await check_user(user_id)
    if not user_data:
        return False
    if reward.get("money"):
        user_data["money"] = int(user_data.get("money") or 0) + reward["money"]
    if reward.get("exp") and user_data.get("career"):
        user_data["career"]["exp"] = user_data["career"].get("exp", 0) + reward["exp"]
    for item in reward.get("items") or []:
        for _ in range(int(item.get("count", 1))):
            user_data.setdefault("backpack", []).append(
                {"name": item.get("name"), "type": item.get("type")},
            )
    await save_user(user_id, user_data)
    return True


async def _check_user(event, action: str) -> dict:
    remaining = cd_remaining(sender_id(event), "career", action)
    if remaining > 0:
        raise CommandError(f"操作太快啦，请等待{remaining}秒后再试")
    from . import base as _guards

    return await _guards.require_player(event)


# -------------------------------------------------------------- commands --
@cmd(r"^#模拟人生职业列表$", name="career_list", priority=1)
async def career_list(self, event):
    """查看全部可选职业"""
    rows = [
        f"{c.get('icon', '')} {c['name']} - {c.get('description', '')}\n"
        f"  基础薪资：{c.get('baseSalary')}元/次"
        for c in game_data.get_all_careers().values()
    ]
    yield (
        "可选职业列表\n\n━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(rows)
        + "\n\n━━━━━━━━━━━━━━━\n\n使用 #选择职业 [职业名] 选择职业"
    )


@cmd(r"^#选择职业.*$", name="career_select", priority=1)
async def career_select(self, event):
    """选择职业：#选择职业 [职业名]"""
    user_id = sender_id(event)
    data = await _check_user(event, "select")
    career_name_arg = event.get_message_str().replace("#选择职业", "").strip()
    career = next(
        (
            c
            for c in game_data.get_all_careers().values()
            if c.get("name") == career_name_arg
        ),
        None,
    )
    if career is None:
        yield "无效的职业！使用 #模拟人生职业列表 查看可选职业"
        return
    if data.get("career"):
        yield f"你已经是{data['career']['name']}了！请先使用 #辞职 再选择新职业。"
        return
    data["career"] = {
        "id": career["id"],
        "name": career["name"],
        "level": 1,
        "exp": 0,
        "totalWork": 0,
        "dailyWork": 0,
        "skills": {},
        "lastWork": 0,
    }
    await save_user(user_id, data)
    set_cd(user_id, "career", "select")
    yield (
        f"恭喜你成为{career['name']}！\n\n"
        f"当前等级：{career['ranks'][0]['title']}\n\n"
        f"基础薪资：{career['baseSalary']}元/次\n\n"
        "使用 #开始工作 开始你的职业生涯！"
    )


@cmd(r"^#职业信息$", name="career_info", priority=1)
async def career_info(self, event):
    """查看职业详情与晋升进度"""
    data = await _check_user(event, "info")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！使用 #模拟人生职业列表 查看可选职业"
        return
    career = game_data.get_career(career_state["id"])
    ranks = career.get("ranks") or []
    current_rank = ranks[career_state["level"] - 1]
    next_rank = (
        ranks[career_state["level"]] if career_state["level"] < len(ranks) else None
    )

    lines = [
        f"{data.get('name')}的职业信息",
        "━━━━━━━━━━━━━━━",
        f"职业：{career.get('icon', '')} {career['name']}",
        f"等级：{current_rank['title']} (Lv.{career_state['level']})",
        f"经验：{career_state['exp']}",
        f"总工作次数：{career_state['totalWork']}次",
        f"今日工作：{career_state['dailyWork']}/{cfg.get('careers.maxDailyWork', 10)}次",
        f"当前薪资：{current_rank['salary']}元/次",
    ]
    if next_rank:
        lines.append("")
        lines.append(f"下一等级：{next_rank['title']}")
        lines.append(f"需要经验：{next_rank.get('requirements', {}).get('exp')}")
    else:
        lines.append("")
        lines.append("已达到最高等级！")
    lines += ["", "━━━━━━━━━━━━━━━", "职业技能："]
    for skill in career.get("skills") or []:
        level = (career_state.get("skills") or {}).get(skill["id"], 0)
        lines.append(f"  {skill['name']}: Lv.{level}/{skill['maxLevel']}")
    yield "\n".join(lines)


@cmd(r"^#开始工作$", name="career_work", priority=1)
async def career_work(self, event):
    """开始工作赚取薪资与经验"""
    user_id = sender_id(event)
    data = await _check_user(event, "work")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！使用 #选择职业 选择职业"
        return
    max_daily = cfg.get("careers.maxDailyWork", 10)
    if career_state["dailyWork"] >= max_daily:
        yield "今日工作次数已达上限！请明天再来。"
        return

    career = game_data.get_career(career_state["id"])
    rank = career["ranks"][career_state["level"] - 1]
    exp_min = cfg.get("careers.expPerWork.min", 10)
    exp_max = cfg.get("careers.expPerWork.max", 30)
    exp_gain = random.randint(int(exp_min), int(exp_max))
    salary = int(rank["salary"] * cfg.get("careers.salaryMultiplier", 1.0))

    data["money"] = int(data.get("money", 0)) + salary
    career_state["exp"] += exp_gain
    career_state["totalWork"] += 1
    career_state["dailyWork"] += 1
    career_state["lastWork"] = int(time.time() * 1000)

    collab_note = ""
    collab = await _load_collab()
    _clean_expired(collab)
    pair = collab.get("pairs", {}).get(user_id)
    if pair:
        synergy = _find_synergy(career_state["id"], pair["partnerCareer"])
        bonus_money = int(salary * synergy["bonus"])
        bonus_exp = int(exp_gain * synergy["bonus"])
        data["money"] += bonus_money
        career_state["exp"] += bonus_exp
        collab_note = (
            f"\n协作加成[{synergy['name']}]：额外金币{bonus_money}，额外经验{bonus_exp}"
        )
        share = int(salary * cfg.get("careers.collab.partnerShare", 0.2))
        if share > 0:
            partner_data = await check_user(pair["partner"])
            if partner_data:
                partner_data["money"] = int(partner_data.get("money") or 0) + share
                await save_user(pair["partner"], partner_data)
                collab_note += f"\n协作伙伴分红：{share}金币已转入伙伴账户"
        await _save_collab(collab)

    await save_user(user_id, data)
    set_cd(user_id, "career", "work")

    work_messages = {
        "doctor": ["成功治疗了一位病人", "完成了查房工作", "开具了处方"],
        "chef": ["制作了一道美味佳肴", "研发了新菜品", "完成了订单"],
        "firefighter": ["扑灭了小火苗", "进行了安全巡查", "训练了体能"],
        "police": ["巡逻了街区", "调解了纠纷", "记录了案件"],
        "fisherman": ["钓到了大鱼", "整理了渔具", "学习了钓鱼技巧"],
        "farmer": ["照料了农作物", "收获了蔬菜", "喂养了牲畜"],
    }
    messages = work_messages.get(career["id"], ["完成了工作"])
    yield (
        f"{random.choice(messages)}！\n\n"
        f"获得薪资：{salary}元\n\n"
        f"获得经验：{exp_gain}\n\n"
        f"今日工作：{career_state['dailyWork']}/{max_daily}次{collab_note}"
    )


@cmd(r"^#职业升级$", name="career_promote", priority=1)
async def career_promote(self, event):
    """晋升职业等级"""
    user_id = sender_id(event)
    data = await _check_user(event, "promote")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！"
        return
    career = game_data.get_career(career_state["id"])
    ranks = career.get("ranks") or []
    if career_state["level"] >= len(ranks):
        yield "你已达到最高等级！"
        return
    next_rank = ranks[career_state["level"]]
    required = next_rank.get("requirements", {}).get("exp", 0)
    if career_state["exp"] < required:
        yield f"经验不足！需要{required}经验，当前{career_state['exp']}"
        return
    career_state["level"] += 1
    bonus = cfg.get("careers.promotionBonus", 500)
    data["money"] = int(data.get("money", 0)) + bonus
    await save_user(user_id, data)
    set_cd(user_id, "career", "promote")
    yield (
        f"恭喜晋升！\n\n新等级：{next_rank['title']}\n\n"
        f"新薪资：{next_rank['salary']}元/次\n\n晋升奖励：{bonus}元"
    )


@cmd(r"^#学习技能.*$", name="career_learn_skill", priority=1)
async def career_learn_skill(self, event):
    """学习/升级职业技能"""
    user_id = sender_id(event)
    data = await _check_user(event, "learn")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！"
        return
    skill_name = event.get_message_str().replace("#学习技能", "").strip()
    career = game_data.get_career(career_state["id"])
    skill = next(
        (s for s in career.get("skills") or [] if s["name"] == skill_name), None
    )
    if skill is None:
        yield "无效的技能！使用 #职业技能 查看可学技能"
        return
    skills = career_state.setdefault("skills", {})
    current_level = skills.get(skill["id"], 0)
    if current_level >= skill["maxLevel"]:
        yield "该技能已达到最高等级！"
        return
    cost = (current_level + 1) * 100
    if int(data.get("money", 0)) < cost:
        yield f"资金不足！需要{cost}元"
        return
    data["money"] = int(data.get("money", 0)) - cost
    skills[skill["id"]] = current_level + 1
    await save_user(user_id, data)
    set_cd(user_id, "career", "learn")
    yield f"学习成功！\n\n{skill['name']}等级：{current_level} 至 {current_level + 1}\n\n花费：{cost}元"


@cmd(r"^#职业技能$", name="career_skills", priority=1)
async def career_skills(self, event):
    """查看职业技能列表"""
    data = await _check_user(event, "skills")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！"
        return
    career = game_data.get_career(career_state["id"])
    rows = []
    for skill in career.get("skills") or []:
        level = (career_state.get("skills") or {}).get(skill["id"], 0)
        rows.append(
            f"{skill['name']}: Lv.{level}/{skill['maxLevel']}\n  {skill.get('description', '')}"
        )
    yield (
        f"{career['name']}技能\n\n━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(rows)
        + "\n\n━━━━━━━━━━━━━━━\n\n使用 #学习技能 [技能名] 提升技能"
    )


@cmd(r"^#辞职$", name="career_resign", priority=1)
async def career_resign(self, event):
    """辞去当前职业"""
    user_id = sender_id(event)
    data = await _check_user(event, "resign")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！"
        return
    old_name = career_state["name"]
    del data["career"]
    await save_user(user_id, data)
    set_cd(user_id, "career", "resign")
    yield f"已辞去{old_name}的工作。使用 #选择职业 选择新职业。"


CAREER_ACTION_NAMES = {
    "doctor": "医生",
    "chef": "厨师",
    "firefighter": "消防员",
    "police": "警察",
}


async def _require_career(event, career_id: str) -> dict:
    data = await _check_user(event, "action")
    data = await _check_user(event, "action")
    career_state = data.get("career")
    label = CAREER_ACTION_NAMES.get(career_id, career_id)
    if not career_state or career_state["id"] != career_id:
        raise CommandError(f"只有{label}才能进行此操作！")
    return data


async def _grant_action_reward(user_id: str, data: dict, money: int, exp: int) -> None:
    data["money"] = int(data.get("money", 0)) + money
    career_state = data.get("career") or {}
    career_state["exp"] = career_state.get("exp", 0) + exp
    await save_user(user_id, data)
    set_cd(user_id, "career", "action")
    data["money"] = int(data.get("money", 0)) + money
    career_state = data.get("career") or {}
    career_state["exp"] = career_state.get("exp", 0) + exp


# ------------------------------------------------------- 医生：真实病例 --
def _diseases() -> list[dict]:
    return game_data._load("doctor/diseases.json") or []


def _medicines() -> list[dict]:
    return game_data._load("doctor/medicines.json") or []


def _surgeries() -> list[dict]:
    return game_data._load("doctor/surgeries.json") or []


@cmd(r"^#诊断.*$", name="diagnose_patient", priority=1)
async def diagnose_patient(self, event):
    """(医生)接诊病人并给出诊断"""
    user_id = sender_id(event)
    data = await _require_career(event, "doctor")
    diseases = _diseases()
    name = event.get_message_str().replace("#诊断", "").strip()
    disease = (
        next((d for d in diseases if d["name"] == name), None)
        if name
        else random.choice(diseases)
    )
    if disease is None:
        yield f"病例档案中没有「{name}」！使用 #诊断 随机接诊。"
        return
    fee = 50 + disease.get("severity", 1) * 50 + random.randint(0, 50)
    exp = 10 + disease.get("severity", 1) * 5
    await _grant_action_reward(user_id, data, fee, exp)
    symptoms = "、".join(disease.get("symptoms") or [])
    treatment = disease.get("treatment") or {}
    medicine_ids = treatment.get("medicines") or []
    med_names = [m.get("name", "") for m in _medicines() if m.get("id") in medicine_ids]
    yield (
        f"【诊断报告】{disease.get('name')}（{disease.get('type', '')}）\n\n"
        f"症状：{symptoms}\n\n"
        f"严重程度：{'★' * disease.get('severity', 1)}\n\n"
        f"推荐用药：{'、'.join(med_names) or '对症治疗'}\n\n"
        f"医嘱：{treatment.get('special_care', '注意休息')}\n\n"
        f"诊疗费 +{fee}元，职业经验 +{exp}"
    )


@cmd(r"^#治疗病人.*$", name="treat_patient", priority=1)
async def treat_patient(self, event):
    """(医生)治疗病人：#治疗病人 [病名]"""
    user_id = sender_id(event)
    data = await _require_career(event, "doctor")
    career_state = data["career"]
    name = event.get_message_str().replace("#治疗病人", "").strip()
    diseases = _diseases()
    disease = (
        next((d for d in diseases if d["name"] == name), None)
        if name
        else random.choice(diseases)
    )
    if disease is None:
        yield f"病例档案中没有「{name}」！"
        return
    severity = disease.get("severity", 1)
    success_rate = min(98, 85 + career_state.get("level", 1) * 2 - severity * 3)
    fee = severity * 200 + random.randint(50, 200)
    exp = 15 + severity * 8
    if random.random() * 100 <= success_rate:
        await _grant_action_reward(user_id, data, fee, exp)
        yield (
            f"你成功治愈了「{disease.get('name')}」病人！\n\n"
            f"治疗费 +{fee}元，职业经验 +{exp}\n\n"
            f"（成功率 {success_rate}%）"
        )
    else:
        loss = fee // 3
        data["money"] = int(data.get("money", 0)) - loss
        await save_user(user_id, data)
        set_cd(user_id, "career", "action")
        yield (
            f"治疗「{disease.get('name')}」时出现并发症，治疗失败……\n\n"
            f"赔偿医疗费 -{loss}元\n\n（成功率 {success_rate}%，提升职阶可提高成功率）"
        )


@cmd(r"^#手术\s*(.+)$", name="perform_surgery", priority=1)
async def perform_surgery(self, event):
    """(医生)执行手术：#手术 [术式名]"""
    user_id = sender_id(event)
    data = await _require_career(event, "doctor")
    career_state = data["career"]
    name = event.get_message_str().replace("#手术", "").strip()
    surgeries = _surgeries()
    surgery = (
        next((s for s in surgeries if s["name"] == name), None)
        if name
        else random.choice(surgeries)
    )
    if surgery is None:
        yield f"手术档案中没有「{name}」！使用 #手术 随机接台手术。"
        return
    required_level = surgery.get("required_level", 1)
    if career_state.get("level", 1) < required_level:
        yield (
            f"「{surgery['name']}」需要职阶达到 Lv.{required_level}，"
            f"你当前 Lv.{career_state.get('level', 1)}。"
        )
        return
    success_rate = surgery.get("success_rate", 70) + career_state.get("level", 1) * 3
    price = surgery.get("price", 3000)
    exp = surgery.get("difficulty", 3) * 15
    if random.random() * 100 <= success_rate:
        await _grant_action_reward(user_id, data, price, exp)
        yield (
            f"🏥 「{surgery['name']}」手术圆满成功！\n\n"
            f"手术费 +{price}元，职业经验 +{exp}\n\n"
            f"（成功率 {min(99, success_rate)}%，耗时{surgery.get('duration', 60)}分钟）"
        )
    else:
        loss = price // 4
        data["money"] = int(data.get("money", 0)) - loss
        await save_user(user_id, data)
        set_cd(user_id, "career", "action")
        yield (
            f"「{surgery['name']}」术中出现突发状况，手术失败……\n\n"
            f"承担医疗责任 -{loss}元\n\n（成功率 {success_rate}%）"
        )


# ------------------------------------------------------- 警察：真实案件 --
def _case_data() -> dict:
    return game_data._load("police/cases.json") or {}


@cmd(r"^#巡逻$", name="patrol_area", priority=1)
async def patrol_area(self, event):
    """(警察)街区巡逻"""
    user_id = sender_id(event)
    data = await _require_career(event, "police")
    locations = (_case_data().get("locations") or {}) or {
        "商业街": {
            "crimeRate": 0.5,
            "difficultyModifier": 1.0,
            "description": "人流密集的街区",
        },
    }
    loc_name = random.choice(list(locations.keys()))
    loc = locations[loc_name]
    fee = 100 + random.randint(0, 100)
    exp = 10
    events = [
        "调解了一起邻里纠纷",
        "帮助迷路老人回家",
        "查处了一起违规占道",
        "进行了一场安全宣传",
    ]
    if random.random() < loc.get("crimeRate", 0.3):
        events = ["当场抓获一名小偷", "制止了一起斗殴", "查处了一起诈骗案"]
        fee += 100
        exp += 5
    await _grant_action_reward(user_id, data, fee, exp)
    yield (
        f"你在{loc_name}巡逻完毕：{random.choice(events)}。\n\n"
        f"出警补贴 +{fee}元，职业经验 +{exp}"
    )


@cmd(r"^#破案.*$", name="solve_case", priority=1)
async def solve_case(self, event):
    """(警察)侦破案件：#破案 [地点(可选)]"""
    user_id = sender_id(event)
    data = await _require_career(event, "police")
    career_state = data["career"]
    case_data = _case_data()
    case_types = case_data.get("caseTypes") or {}
    locations = case_data.get("locations") or {}
    if not case_types:
        yield "案件档案库为空！"
        return
    loc_name = event.get_message_str().replace("#破案", "").strip()
    if loc_name and loc_name not in locations:
        yield f"辖区没有「{loc_name}」！可选：{'、'.join(locations.keys())}"
        return
    case_name = random.choice(list(case_types.keys()))
    case = case_types[case_name]
    if not loc_name:
        loc_name = random.choice(list(locations.keys()))
    loc = locations.get(loc_name, {})
    difficulty = random.choice(
        list(
            (
                case.get("difficulties")
                or {"普通": {"expMultiplier": 1.5, "rewardMultiplier": 1.5}}
            ).keys()
        )
    )
    diff_cfg = case["difficulties"][difficulty]
    level_bonus = career_state.get("level", 1) * 5
    # 地区难度修正：difficultyModifier 越高（治安越乱），破案越难
    loc_modifier = int((loc.get("difficultyModifier", 1.0) - 1.0) * 30)
    success_rate = max(
        30,
        min(
            98,
            80
            + level_bonus
            - int((difficulty == "极难") * 25)
            - int(difficulty == "困难") * 12
            - loc_modifier,
        ),
    )
    reward = int(case.get("baseReward", 500) * diff_cfg.get("rewardMultiplier", 1))
    exp = int(case.get("baseExp", 50) * diff_cfg.get("expMultiplier", 1))
    if random.random() * 100 <= success_rate:
        await _grant_action_reward(user_id, data, reward, exp)
        yield (
            f"🔍 你在{loc_name}成功侦破了一起{case_name}（{difficulty}）！\n\n"
            f"悬赏 +{reward}元，职业经验 +{exp}\n\n"
            f"（破案成功率 {success_rate}%）"
        )
    else:
        exp = exp // 3
        career_state = data.get("career") or {}
        career_state["exp"] = career_state.get("exp", 0) + exp
        await save_user(user_id, data)
        set_cd(user_id, "career", "action")
        yield (
            f"{case_name}线索中断，案件陷入僵局……\n\n"
            f"仅获得少量经验 +{exp}\n\n（破案成功率 {success_rate}%）"
        )


# ------------------------------------------------- 消防：真实火情/救援 --
def _fire_types() -> dict:
    return game_data._load("firefighter/fireTypes.json") or {}


def _rescue_types() -> dict:
    return game_data._load("firefighter/rescueTypes.json") or {}


async def _fire_action(event, kind: str):
    user_id = sender_id(event)
    data = await _require_career(event, "firefighter")
    user_id = sender_id(event)
    data = await _require_career(event, "firefighter")
    career_state = data["career"]
    pool = _fire_types() if kind == "fire" else _rescue_types()
    if not pool:
        raise CommandError("任务档案库为空！")
    task_name = (
        event.get_message_str().replace("#灭火", "").replace("#救援", "").strip()
    )
    task = next((v for v in pool.values() if v.get("name") == task_name), None)
    if task is None:
        task = random.choice(list(pool.values()))
    danger = task.get("danger", 1)
    success_rate = max(35, min(98, 95 - danger * 6 + career_state.get("level", 1) * 4))
    reward = task.get("moneyReward", 100)
    exp = task.get("xpReward", 50)
    if random.random() * 100 <= success_rate:
        await _grant_action_reward(user_id, data, reward, exp)
        return (
            f"🚒 「{task.get('name')}」任务完成！\n\n"
            f"{task.get('description', '')}\n\n"
            f"任务奖励 +{reward}元，职业经验 +{exp}\n\n"
            f"（成功率 {success_rate}%，危险等级 {'🔥' * danger}）"
        )
    loss = reward // 3
    data["money"] = int(data.get("money", 0)) - loss
    return (
        f"「{task.get('name')}」现场突发险情，任务被迫中止……\n\n"
        f"装备损耗 -{loss}元\n\n"
        f"（成功率 {success_rate}%，危险等级 {'🔥' * danger}，量力而行！）"
    )


@cmd(r"^#灭火.*$", name="extinguish_fire", priority=1)
async def extinguish_fire(self, event):
    """(消防员)执行灭火任务：#灭火 [火情(可选)]"""
    yield await _fire_action(event, "fire")


@cmd(r"^#救援.*$", name="rescue_mission", priority=1)
async def rescue_mission(self, event):
    """(消防员)执行救援任务：#救援 [类型(可选)]"""
    yield await _fire_action(event, "rescue")


# ---------------------------------------------------------------- collab --
@cmd(r"^#发起协作.*$", name="collab_invite", priority=1)
async def collab_invite(self, event):
    """发布协作邀请：#发起协作 [需求职业(可选)]"""
    user_id = sender_id(event)
    data = await _check_user(event, "collab")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！使用 #选择职业 选择职业后再发起协作"
        return
    collab = await _load_collab()
    _clean_expired(collab)
    if collab.get("pairs", {}).get(user_id):
        partner_career = collab["pairs"][user_id]["partnerCareer"]
        yield (
            f"你已与{_career_name(partner_career)}玩家结成协作关系，"
            "发送 #解除协作 后可重新发起"
        )
        return
    need_name = event.get_message_str().replace("#发起协作", "").strip()
    need = "any"
    if need_name:
        target = next(
            (
                c
                for c in game_data.get_all_careers().values()
                if c.get("name") == need_name
            ),
            None,
        )
        if target is None:
            yield "无效的职业！使用 #模拟人生职业列表 查看可选职业"
            return
        if target["id"] == career_state["id"]:
            yield "协作需要与不同职业的玩家组队，请选择其他职业"
            return
        need = target["id"]
    collab["invites"] = [
        i for i in collab.get("invites", []) if i.get("from") != user_id
    ]
    collab["seq"] = collab.get("seq", 0) + 1
    ttl = cfg.get("careers.collab.inviteTtl", 600)
    collab.setdefault("invites", []).append(
        {
            "id": collab["seq"],
            "from": user_id,
            "fromName": data.get("name") or user_id,
            "fromCareer": career_state["id"],
            "need": need,
            "expire": time.time() * 1000 + ttl * 1000,
        },
    )
    await _save_collab(collab)
    set_cd(user_id, "career", "collab")
    need_text = "任意其他职业" if need == "any" else _career_name(need)
    yield (
        "协作邀请已发布\n\n"
        f"编号：{collab['seq']}\n\n"
        f"发起方：{_career_name(career_state['id'])}\n\n"
        f"需求职业：{need_text}\n\n"
        f"有效期：{ttl // 60}分钟\n\n"
        "其他玩家发送 #响应协作 编号 即可结成协作关系"
    )


@cmd(r"^#响应协作.*$", name="collab_accept", priority=1)
async def collab_accept(self, event):
    """响应协作邀请：#响应协作 编号"""
    user_id = sender_id(event)
    data = await _check_user(event, "collab")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！使用 #选择职业 选择职业后再响应协作"
        return
    id_text = event.get_message_str().replace("#响应协作", "").strip()
    collab = await _load_collab()
    _clean_expired(collab)
    if collab.get("pairs", {}).get(user_id):
        yield "你已处于协作关系中，发送 #解除协作 后可响应新邀请"
        return
    invite = next(
        (i for i in collab.get("invites", []) if str(i.get("id")) == id_text), None
    )
    if invite is None:
        yield "邀请不存在或已过期，发送 #职业协作 查看当前可响应的邀请"
        return
    if invite["from"] == user_id:
        yield "不能响应自己发布的协作邀请"
        return
    if invite["fromCareer"] == career_state["id"]:
        yield "协作需要不同职业组队，你的职业与发起方相同"
        return
    if invite["need"] != "any" and invite["need"] != career_state["id"]:
        yield f"该邀请需要{_career_name(invite['need'])}职业玩家响应"
        return
    hours = cfg.get("careers.collab.pairHours", 12)
    until = time.time() * 1000 + hours * 3600 * 1000
    collab.setdefault("pairs", {})[user_id] = {
        "partner": invite["from"],
        "partnerCareer": invite["fromCareer"],
        "until": until,
    }
    collab["pairs"][invite["from"]] = {
        "partner": user_id,
        "partnerCareer": career_state["id"],
        "until": until,
    }
    collab["invites"] = [
        i
        for i in collab.get("invites", [])
        if i.get("id") != invite["id"]
        and i.get("from") != invite["from"]
        and i.get("from") != user_id
    ]
    _bump_stat(collab, user_id, "collabCount")
    _bump_stat(collab, invite["from"], "collabCount")
    await _save_collab(collab)
    set_cd(user_id, "career", "collab")
    synergy = _find_synergy(career_state["id"], invite["fromCareer"])
    share_pct = round(cfg.get("careers.collab.partnerShare", 0.2) * 100)
    yield (
        "协作关系结成\n\n"
        f"{_career_name(invite['fromCareer'])} × {_career_name(career_state['id'])}\n\n"
        f"触发能力互补：{synergy['name']}\n\n"
        f"{synergy['desc']}\n\n"
        f"协作加成：工作收益提升{round(synergy['bonus'] * 100)}%，"
        f"伙伴可获{share_pct}%分红\n\n"
        f"有效期：{hours}小时\n\n"
        "发送 #联动任务 查看跨职业任务链"
    )


@cmd(r"^#职业协作$", name="collab_hall", priority=1)
async def collab_hall(self, event):
    """查看职业协作大厅"""
    user_id = sender_id(event)
    data = await _check_user(event, "collab")
    collab = await _load_collab()
    _clean_expired(collab)
    await _save_collab(collab)

    lines = ["职业协作大厅", ""]
    pair = collab.get("pairs", {}).get(user_id)
    if pair:
        synergy = _find_synergy(
            (data.get("career") or {}).get("id", ""), pair["partnerCareer"]
        )
        remain = max(0, int((pair["until"] - time.time() * 1000) / 60000))
        lines.append(f"当前协作：{_career_name(pair['partnerCareer'])}玩家")
        lines.append(
            f"互补效果：{synergy['name']}，工作收益+{round(synergy['bonus'] * 100)}%"
        )
        lines.append(f"剩余时间：{remain // 60}小时{remain % 60}分钟")
        lines.append("发送 #解除协作 可终止当前协作")
    else:
        lines.append("当前协作：无")
        lines.append("发送 #发起协作 职业名(可选) 发布协作邀请")
    lines.append("")
    lines.append("可响应的邀请")
    open_invites = [i for i in collab.get("invites", []) if i.get("from") != user_id]
    if not open_invites:
        lines.append("暂无邀请")
    else:
        for invite in open_invites[:8]:
            need_text = (
                "任意职业" if invite["need"] == "any" else _career_name(invite["need"])
            )
            lines.append(
                f"编号{invite['id']} {_career_name(invite['fromCareer'])} 需求{need_text}",
            )
        lines.append("发送 #响应协作 编号 结成协作")
    lines.append("")
    lines.append("能力互补一览")
    for synergy in cfg.get("careers.synergies", []) or []:
        careers = synergy.get("careers") or []
        if len(careers) >= 2:
            lines.append(
                f"{_career_name(careers[0])}×{_career_name(careers[1])} "
                f"{synergy['name']} +{round(synergy['bonus'] * 100)}%",
            )
    yield "\n".join(lines)


@cmd(r"^#解除协作$", name="collab_leave", priority=1)
async def collab_leave(self, event):
    """解除当前协作关系"""
    user_id = sender_id(event)
    await _check_user(event, "collab")
    collab = await _load_collab()
    _clean_expired(collab)
    pair = collab.get("pairs", {}).get(user_id)
    if not pair:
        yield "你当前没有协作关系"
        return
    del collab["pairs"][user_id]
    collab.get("pairs", {}).pop(pair["partner"], None)
    await _save_collab(collab)
    set_cd(user_id, "career", "collab")
    yield "协作关系已解除"


# ----------------------------------------------------------------- chain --
def _chains() -> list[dict]:
    return cfg.get("careers.chains", []) or []


@cmd(r"^#联动任务.*$", name="chain_view", priority=1)
async def chain_view(self, event):
    """查看/切换跨职业联动任务链"""
    user_id = sender_id(event)
    data = await _check_user(event, "chain")
    chains = _chains()
    if not chains:
        yield "当前没有开放的联动任务链"
        return
    collab = await _load_collab()
    state = _chain_state(collab, user_id)
    arg = event.get_message_str().replace("#联动任务", "").strip()
    if arg:
        try:
            idx = int(arg)
        except ValueError:
            idx = 0
        if idx < 1 or idx > len(chains):
            yield f"无效的任务链编号，可选范围1至{len(chains)}"
            return
        state["active"] = chains[idx - 1]["id"]
        await _save_collab(collab)
    if not state.get("active") or not any(c["id"] == state["active"] for c in chains):
        first_open = next(
            (
                c
                for c in chains
                if not (state.get("progress", {}).get(c["id"]) or {}).get("done")
            ),
            chains[0],
        )
        state["active"] = first_open["id"]
        await _save_collab(collab)

    lines = ["跨职业联动任务链", ""]
    for i, chain in enumerate(chains):
        progress = state.get("progress", {}).get(chain["id"]) or {
            "node": 0,
            "done": False,
        }
        if chain["id"] == state["active"]:
            mark = "(进行中)"
        elif progress.get("done"):
            mark = "(已完成)"
        else:
            mark = ""
        lines.append(f"{i + 1}.{chain['name']} {mark}")
        lines.append(f"  {chain.get('desc', '')}")
        node_count = len(chain.get("nodes") or [])
        done_text = node_count if progress.get("done") else progress.get("node", 0)
        lines.append(
            f"  进度 {done_text}/{node_count}，"
            f"最终奖励 {_reward_brief(chain.get('finalReward') or {})}",
        )
    lines.append("")

    chain = next(c for c in chains if c["id"] == state["active"])
    progress = state.get("progress", {}).get(chain["id"]) or {"node": 0, "done": False}
    nodes = chain.get("nodes") or []
    if progress.get("done"):
        lines.append(
            f"当前任务链[{chain['name']}]已全部完成，发送 #联动任务 编号 切换其他任务链",
        )
    else:
        node = nodes[progress["node"]]
        lines.append(f"当前节点 {progress['node'] + 1}/{len(nodes)}：{node['name']}")
        lines.append(f"需求职业：{_career_name(node['career'])}")
        lines.append(node.get("desc", ""))
        lines.append(f"节点奖励：{_reward_brief(node.get('reward') or {})}")
        if (data.get("career") or {}).get("id") == node["career"]:
            lines.append("你的职业符合要求，发送 #完成联动节点 提交")
        else:
            lines.append("你的职业不符，可发送 #联动委托 邀请协作伙伴承接该节点")
    yield "\n".join(lines)


async def _finish_chain_node(
    collab, state, chain, progress, owner_id, taker_id, cd_user
):
    node = (chain.get("nodes") or [])[progress["node"]]
    await _grant_chain_reward(owner_id, node.get("reward") or {})
    if taker_id:
        await _grant_chain_reward(taker_id, node.get("reward") or {})
    node = (chain.get("nodes") or [])[progress["node"]]
    progress["node"] += 1
    final_note = ""
    if progress["node"] >= len(chain.get("nodes") or []):
        progress["done"] = True
        await _grant_chain_reward(owner_id, chain.get("finalReward") or {})
        _bump_stat(collab, owner_id, "chainDone")
        if taker_id:
            await _grant_chain_reward(taker_id, chain.get("finalReward") or {})
            _bump_stat(collab, taker_id, "chainDone")
        final_note = (
            f"\n任务链[{chain['name']}]全部完成，"
            f"最终奖励 {_reward_brief(chain.get('finalReward') or {})} 已发放"
        )
    state.setdefault("progress", {})[chain["id"]] = progress
    await _save_collab(collab)
    set_cd(cd_user, "career", "chain")
    lines = [f"联动节点[{node['name']}]完成"]
    lines.append(
        f"节点奖励 {_reward_brief(node.get('reward') or {})} 已发放"
        + ("给委托双方" if taker_id else ""),
    )
    if taker_id:
        lines.append("跨职业承接成功，协作亲密度提升")
    lines.append(
        f"任务链进度 {progress['node']}/{len(chain.get('nodes') or [])}{final_note}"
    )
    if not progress.get("done"):
        nxt = chain["nodes"][progress["node"]]
        lines.append(f"下一节点：{nxt['name']}，需求职业 {_career_name(nxt['career'])}")
    return "\n".join(lines)


@cmd(r"^#完成联动节点$", name="chain_complete", priority=1)
async def chain_complete(self, event):
    """完成当前联动节点"""
    user_id = sender_id(event)
    data = await _check_user(event, "chain")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！"
        return
    chains = _chains()
    collab = await _load_collab()
    state = _chain_state(collab, user_id)
    chain = next((c for c in chains if c["id"] == state.get("active")), None)
    if chain is None:
        yield "请先发送 #联动任务 选择任务链"
        return
    progress = state.get("progress", {}).get(chain["id"]) or {"node": 0, "done": False}
    if progress.get("done"):
        yield "当前任务链已完成，发送 #联动任务 编号 切换其他任务链"
        return
    node = chain["nodes"][progress["node"]]
    if career_state["id"] != node["career"]:
        yield (
            f"当前节点需要{_career_name(node['career'])}完成，你的职业不符，"
            "可发送 #联动委托 邀请协作伙伴承接"
        )
        return
    yield await _finish_chain_node(collab, state, chain, progress, user_id, "", user_id)


@cmd(r"^#联动委托$", name="chain_delegate", priority=1)
async def chain_delegate(self, event):
    """委托协作伙伴承接当前节点"""
    user_id = sender_id(event)
    data = await _check_user(event, "chain")
    chains = _chains()
    collab = await _load_collab()
    _clean_expired(collab)
    state = _chain_state(collab, user_id)
    chain = next((c for c in chains if c["id"] == state.get("active")), None)
    if chain is None:
        yield "请先发送 #联动任务 选择任务链"
        return
    progress = state.get("progress", {}).get(chain["id"]) or {"node": 0, "done": False}
    if progress.get("done"):
        yield "当前任务链已完成"
        return
    node = chain["nodes"][progress["node"]]
    if (data.get("career") or {}).get("id") == node["career"]:
        yield "你的职业符合当前节点要求，直接发送 #完成联动节点 即可"
        return
    pair = collab.get("pairs", {}).get(user_id)
    if not pair:
        yield "你还没有协作伙伴，发送 #发起协作 先组建协作关系"
        return
    if pair["partnerCareer"] != node["career"]:
        yield (
            f"当前节点需要{_career_name(node['career'])}，"
            f"你的协作伙伴职业为{_career_name(pair['partnerCareer'])}，无法承接"
        )
        return
    collab["takeovers"] = [
        t
        for t in collab.get("takeovers", [])
        if not (t.get("owner") == user_id and t.get("chainId") == chain["id"])
    ]
    collab.setdefault("takeovers", []).append(
        {
            "owner": user_id,
            "chainId": chain["id"],
            "node": progress["node"],
            "to": pair["partner"],
            "expire": time.time() * 1000
            + cfg.get("careers.collab.takeoverTtl", 900) * 1000,
        },
    )
    await _save_collab(collab)
    set_cd(user_id, "career", "chain")
    yield (
        f"已向协作伙伴发出节点承接委托\n节点：{node['name']}\n"
        "伙伴发送 #承接联动节点 即可代你完成该节点"
    )


@cmd(r"^#承接联动节点$", name="chain_takeover", priority=1)
async def chain_takeover(self, event):
    """承接伙伴委托的联动节点"""
    user_id = sender_id(event)
    data = await _check_user(event, "chain")
    career_state = data.get("career")
    if not career_state:
        yield "你还没有职业！"
        return
    chains = _chains()
    collab = await _load_collab()
    _clean_expired(collab)
    req = next((t for t in collab.get("takeovers", []) if t.get("to") == user_id), None)
    if req is None:
        yield "当前没有需要你承接的联动节点"
        return
    chain = next((c for c in chains if c["id"] == req["chainId"]), None)
    if chain is None:
        collab["takeovers"] = [t for t in collab["takeovers"] if t is not req]
        await _save_collab(collab)
        yield "委托对应的任务链已失效"
        return
    node = (
        (chain.get("nodes") or [None])[req["node"]]
        if req["node"] < len(chain.get("nodes") or [])
        else None
    )
    if node is None or career_state["id"] != node["career"]:
        yield f"该节点需要{_career_name(node['career']) if node else '未知'}，你的职业不符"
        return
    owner_state = _chain_state(collab, req["owner"])
    progress = owner_state.get("progress", {}).get(chain["id"]) or {
        "node": 0,
        "done": False,
    }
    if progress.get("done") or progress["node"] != req["node"]:
        collab["takeovers"] = [t for t in collab["takeovers"] if t is not req]
        await _save_collab(collab)
        yield "该委托已被处理"
        return
    collab["takeovers"] = [t for t in collab["takeovers"] if t is not req]
    _bump_stat(collab, user_id, "takeoverDone")
    yield _finish_chain_node(
        collab, owner_state, chain, progress, req["owner"], user_id, user_id
    )


async def daily_reset() -> None:
    for user_id, user_data in (await load_all_users()).items():
        if user_data.get("career"):
            user_data["career"]["dailyWork"] = 0
            await save_user(user_id, user_data)
