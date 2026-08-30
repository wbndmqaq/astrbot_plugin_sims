"""新手引导 - port of ``apps/新手引导.js``.

Staged onboarding walkthrough; per-user progress persists in plugin data
and stage rewards are granted to the player archive.
"""

from __future__ import annotations

import time
from typing import Any

from ..core import config as cfg
from ..core.context import sender_id
from ..core.db import check_user, get_store, save_user
from ..core.renderer import renderer
from .base import cmd

DEFAULT_STAGES = [
    {
        "id": "stage_1",
        "name": "初入小镇",
        "reward": {"money": 500, "stamina": 50},
        "steps": [
            {
                "title": "创建属于你的角色",
                "scene": "初来乍到",
                "action": "发送 #开始模拟人生 创建角色档案",
                "highlight": "#开始模拟人生",
                "points": ["获得初始 1000 金币与 100 体力", "每日可签到领取丰厚奖励"],
            },
            {
                "title": "查看个人属性面板",
                "scene": "认识自己",
                "action": "发送 #模拟人生信息",
                "highlight": "#模拟人生信息",
                "points": ["随时查看健康、心情与饱食度", "合理调配体力与时间"],
            }
        ],
    },
    {
        "id": "stage_2",
        "name": "职场起步",
        "reward": {"money": 1000, "items": [{"name": "小型体力药水", "count": 2}]},
        "steps": [
            {
                "title": "选择你的第一份职业",
                "scene": "人才市场",
                "action": "发送 #模拟人生职业列表 并选择职业",
                "highlight": "#选择职业 厨师",
                "points": ["入职后可工作赚取薪资", "累积经验晋升更高职阶"],
            }
        ],
    },
]


def _flat_steps() -> tuple[list[dict], list[dict]]:
    stages = cfg.get("guide.stages") or DEFAULT_STAGES
    flat: list[dict] = []
    for si, stage in enumerate(stages):
        steps = stage.get("steps", []) or []
        for ti, step in enumerate(steps):
            flat.append({"stage": stage, "si": si, "ti": ti, "step": step})
    return stages, flat


async def _load_progress(user_id: str) -> dict[str, Any]:
    default: dict[str, Any] = {
        "step": 0,
        "finished": False,
        "claimed": [],
        "updatedAt": 0,
    }
    data = await get_store().read_kv(f"guide_{user_id}", None)
    if isinstance(data, dict):
        return {**default, **data}
    return default


async def _save_progress(user_id: str, data: dict[str, Any]) -> None:
    data["updatedAt"] = int(time.time() * 1000)
    await get_store().write_kv(f"guide_{user_id}", data)


def _reward_text(reward: dict | None) -> str:
    if not reward:
        return ""
    parts = []
    if reward.get("money"):
        parts.append(f"金币x{reward['money']}")
    if reward.get("stamina"):
        parts.append(f"体力x{reward['stamina']}")
    for item in reward.get("items") or []:
        parts.append(f"{item.get('name')}x{item.get('count', 1)}")
    return f"阶段奖励 {' '.join(parts)}" if parts else ""


async def _grant_reward(user_id: str, reward: dict) -> bool:
    user_data = await check_user(user_id)
    if not user_data:
        return False
    if reward.get("money"):
        user_data["money"] = int(user_data.get("money", 0)) + int(reward["money"])
    if reward.get("stamina"):
        user_data["stamina"] = min(
            100,
            int(user_data.get("stamina", 0)) + int(reward["stamina"]),
        )
    for item in reward.get("items") or []:
        for _ in range(int(item.get("count", 1))):
            user_data.setdefault("backpack", []).append(
                {"name": item.get("name"), "type": item.get("type")},
            )
    await save_user(user_id, user_data)
    return True


async def _render_step(event, progress: dict) -> None:
    stages, flat = _flat_steps()
    total = len(flat)
    cur = flat[min(progress["step"], total - 1)]
    stage = cur["stage"]
    dots = [i <= cur["ti"] for i in range(len(stage.get("steps") or []))]
    path = await renderer.render_image(
        "guide",
        {
            "stageName": stage.get("name"),
            "stageIndex": cur["si"] + 1,
            "stageTotal": len(stages),
            "title": cur["step"].get("title"),
            "scene": cur["step"].get("scene"),
            "action": cur["step"].get("action"),
            "highlight": cur["step"].get("highlight"),
            "points": cur["step"].get("points") or [],
            "dots": dots,
            "rewardText": _reward_text(stage.get("reward")),
            "stepGlobal": progress["step"] + 1,
            "stepTotal": total,
            "pct": round(((progress["step"] + 1) / max(total, 1)) * 100),
            "hints": ["#引导下一步", "#引导进度", "#跳过引导"],
        },
    )
    return event.image_result(path)


@cmd(r"^#新手引导$", name="show_guide")
async def show_guide(self, event):
    """开始/继续分阶段新手引导"""
    if not cfg.get("guide.enabled", True):
        return
    progress = await _load_progress(sender_id(event))
    if progress["finished"]:
        yield (
            "你已经完成全部新手引导，可在 #引导进度 中回顾各阶段内容。\n"
            "发送 #模拟人生菜单 查看全部功能。"
        )
        return
    yield await _render_step(event, progress)


@cmd(r"^#引导下一步$", name="guide_next_step")
async def guide_next_step(self, event):
    """推进到下一个引导节点"""
    if not cfg.get("guide.enabled", True):
        return
    user_id = sender_id(event)
    progress = await _load_progress(user_id)
    if progress["finished"]:
        yield "引导已全部完成，无法继续推进。"
        return
    stages, flat = _flat_steps()
    cur = flat[progress["step"]]
    stage = cur["stage"]
    is_stage_end = cur["ti"] == len(stage.get("steps") or []) - 1
    is_last = progress["step"] >= len(flat) - 1
    notice = ""
    if is_stage_end and stage.get("id") not in progress["claimed"]:
        ok = await _grant_reward(user_id, stage.get("reward") or {})
        progress["claimed"].append(stage.get("id"))
        reward_txt = _reward_text(stage.get("reward")) or "获得阶段奖励"
        if ok:
            notice = f"\n完成阶段[{stage['name']}]，{reward_txt}已发放"
        else:
            notice = (
                f"\n完成阶段[{stage['name']}]，检测到尚未创建角色，奖励暂无法发放，"
                "发送 #开始模拟人生 创建角色后可继续游戏"
            )
    if is_last:
        progress["finished"] = True
        progress["step"] = len(flat) - 1
        await _save_progress(user_id, progress)
        yield (
            f"新手引导全部完成，新手大礼包已收入囊中。{notice}\n"
            "发送 #我的成就 查看成长足迹，发送 #抽奖 使用新手抽奖券。"
        )
        return
    progress["step"] += 1
    await _save_progress(user_id, progress)
    if notice:
        yield notice.strip()
    yield await _render_step(event, progress)


@cmd(r"^#跳过引导$", name="skip_guide")
async def skip_guide(self, event):
    """跳过新手引导"""
    user_id = sender_id(event)
    progress = await _load_progress(user_id)
    if progress["finished"]:
        yield "你已经完成过新手引导。"
        return
    progress["finished"] = True
    await _save_progress(user_id, progress)
    yield (
        "已跳过新手引导，阶段奖励将不再补发。\n"
        "可随时发送 #模拟人生菜单 查看功能，发送 #模拟人生帮助 获取玩法说明。"
    )


@cmd(r"^#引导进度$", name="guide_progress")
async def guide_progress(self, event):
    """查看新手引导完成进度"""
    user_id = sender_id(event)
    progress = await _load_progress(user_id)
    stages, flat = _flat_steps()
    done_count = len(flat) if progress["finished"] else progress["step"]
    lines = ["新手引导进度", ""]
    cursor = 0
    for si, stage in enumerate(stages):
        steps_len = len(stage.get("steps") or [])
        stage_done = progress["finished"] or stage.get("id") in progress["claimed"]
        if stage_done:
            mark = "[已完成]"
        elif cursor <= progress["step"] < cursor + steps_len:
            mark = "[进行中]"
        else:
            mark = "[未解锁]"
        lines.append(f"{si + 1}.{stage['name']} {mark}")
        if not stage_done and cursor <= progress["step"] < cursor + steps_len:
            ti = progress["step"] - cursor
            lines.append(f"  当前节点 {(stage['steps'] or [{}])[ti].get('title')}")
        cursor += steps_len
    lines.append("")
    lines.append(f"总进度 {done_count}/{len(flat)}")
    lines.append(
        "状态 已完成" if progress["finished"] else "发送 #新手引导 可断点续看",
    )
    yield "\n".join(lines)
