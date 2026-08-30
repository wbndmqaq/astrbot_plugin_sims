"""管理命令 - port of ``设置.js`` / ``反作弊开关.js`` / ``防作弊系统.js``.

Admin config management (master only), anti-cheat toggle, ban management
and data integrity reports.  The Yunzai ``#更新`` command becomes an
AstrBot-oriented guidance reply since updates are handled by the WebUI.
"""

from __future__ import annotations

import random
import time
from datetime import datetime

from ..core import config as cfg
from ..core.db import (
    db,
    load_all_users,
)
from .base import cmd


async def load_ban_list() -> dict[str, int]:
    return await db.read_kv("ban_list", {}) or {}


async def save_ban_list(bans: dict[str, int]) -> None:
    await db.write_kv("ban_list", bans)


async def ban_user(user_id: str, days: int = 7) -> tuple[int, int]:
    bans = await load_ban_list()
    until = int(time.time() * 1000) + days * 86400 * 1000
    bans[str(user_id)] = until
    await save_ban_list(bans)
    return until, days


async def unban_user(user_id: str) -> bool:
    bans = await load_ban_list()
    if str(user_id) in bans:
        del bans[str(user_id)]
        await save_ban_list(bans)
        return True
    return False


async def is_anti_cheat_enabled() -> bool:
    val = await db.read_kv("anticheat_status", "enabled")
    return val == "enabled"


async def set_anti_cheat_enabled(enabled: bool) -> None:
    await db.write_kv("anticheat_status", "enabled" if enabled else "disabled")


def _config_files() -> list[str]:
    return ["_conf_schema.json"]


def _is_master(event) -> bool:
    try:
        return bool(event.is_admin or event.is_master)
    except Exception:
        return False


# ----------------------------------------------------------------- 设置 --
@cmd(r"^#模拟人生设置$", name="settings_show", priority=600)
async def settings_show(self, event):
    """(管理员)显示设置菜单"""
    if not _is_master(event):
        yield "只有机器人主人才能使用设置功能"
        return
    files = _config_files()
    try:
        from ..core.renderer import renderer, resources_uri

        path = await renderer.render_image(
            "settings",
            {
                "configFiles": files,
                "data": {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                "pluResPath": resources_uri(),
            },
        )
        yield event.image_result(path)
    except Exception:
        pass
    yield (
        "【模拟人生设置】\n\n"
        f"可用配置文件：{'、'.join(files)}\n\n"
        "1. #查看配置 [配置文件名] - 查看完整配置文件\n"
        "2. #查看配置项 [配置文件名] [配置项路径] - 查看特定配置项\n"
        "3. #修改配置 [配置文件名] [配置项路径] [新值] - 修改配置项\n"
        "4. #重置配置 [配置文件名] - 重置配置文件到默认值\n\n"
        "注意: 所有设置功能仅机器人主人可用"
    )


@cmd(r"^#查看配置\s*(.+)?$", name="settings_view", priority=600)
async def settings_view(self, event):
    """(管理员)查看配置文件内容"""
    if not _is_master(event):
        yield "只有机器人主人才能查看配置文件"
        return
    import re

    match = re.match(r"^#查看配置\s*(.*)$", event.get_message_str().strip())
    config_name = (match.group(1) if match else "").strip()
    if not config_name:
        yield f"请指定要查看的配置文件名称，可用的配置文件：{'、'.join(_config_files())}"
        return
    config = cfg.get(config_name)
    if not config:
        yield f"未找到配置文件: {config_name}.yaml"
        return
    import yaml

    config_str = yaml.dump(config, allow_unicode=True, sort_keys=False)
    max_length = 1000
    if len(config_str) <= max_length:
        yield f"{config_name}.yaml 配置内容：\n{config_str}"
        return
    parts = (len(config_str) + max_length - 1) // max_length
    for i in range(parts):
        part = config_str[i * max_length : (i + 1) * max_length]
        yield f"{config_name}.yaml 配置内容 ({i + 1}/{parts})：\n{part}"


@cmd(r"^#查看配置项\s+([\w_]+)\s+(.+)$", name="settings_view_item", priority=600)
async def settings_view_item(self, event):
    """(管理员)查看特定配置项"""
    if not _is_master(event):
        yield "只有机器人主人才能查看配置项"
        return
    import re

    match = re.match(
        r"^#查看配置项\s+([\w_]+)\s+(.+)$",
        event.get_message_str().strip(),
    )
    if not match:
        yield "命令格式不正确，请使用：#查看配置项 [配置文件名] [配置项路径]"
        return
    config_name, item_path = match.group(1), match.group(2)
    value = cfg.get(f"{config_name}.{item_path}")
    if value is None:
        yield f"配置项 {item_path} 不存在于 {config_name}.yaml 中"
        return
    if isinstance(value, (dict, list)):
        import yaml

        yield f"配置项 {item_path} 的值：\n{yaml.dump(value, allow_unicode=True, sort_keys=False)}"
    else:
        yield f"配置项 {item_path} 的值：{value}"


@cmd(r"^#修改配置\s+([\w_]+)\s+(.+)\s+(.+)$", name="settings_modify", priority=600)
async def settings_modify(self, event):
    """(管理员)修改配置项"""
    if not _is_master(event):
        yield "只有机器人主人才能修改配置"
        return
    import re

    match = re.match(
        r"^#修改配置\s+([\w_]+)\s+(.+)\s+(.+)$",
        event.get_message_str().strip(),
    )
    if not match:
        yield "命令格式不正确，请使用：#修改配置 [配置文件名] [配置项路径] [新值]"
        return
    config_name, item_path, new_value = match.groups()
    if cfg.get(config_name) is None:
        yield f"未找到配置文件: {config_name}.yaml"
        return
    parsed: object = new_value
    if new_value == "true":
        parsed = True
    elif new_value == "false":
        parsed = False
    else:
        try:
            parsed = int(new_value)
        except ValueError:
            try:
                parsed = float(new_value)
            except ValueError:
                pass
    cfg.set(f"{config_name}.{item_path}", parsed)
    cfg.reload()
    yield f"已成功修改配置项 {item_path} 的值为 {parsed}"


@cmd(r"^#重置配置\s+([\w_]+)$", name="settings_reset", priority=600)
async def settings_reset(self, event):
    """(管理员)重置配置文件到默认值"""
    if not _is_master(event):
        yield "只有机器人主人才能重置配置"
        return
    import re

    match = re.match(r"^#重置配置\s+([\w_]+)$", event.get_message_str().strip())
    if not match:
        yield "命令格式不正确，请使用：#重置配置 [配置文件名]"
        return
    config_name = match.group(1)
    if config_name not in _config_files():
        yield f"未找到配置文件: {config_name}.yaml，无法重置"
        return
    cfg.delete(config_name)
    cfg.reload()
    yield f"已成功将 {config_name}.yaml 重置为默认配置"


@cmd(r"^#模拟人生配置帮助$", name="settings_help", priority=600)
async def settings_help(self, event):
    """查看配置系统帮助"""
    yield (
        "【模拟人生配置系统帮助】\n"
        "1. #模拟人生设置 - 显示设置菜单\n"
        "2. #查看配置 [配置文件名] - 查看完整配置文件\n"
        "3. #查看配置项 [配置文件名] [配置项路径] - 查看特定配置项\n"
        "4. #修改配置 [配置文件名] [配置项路径] [新值] - 修改配置项\n"
        "5. #重置配置 [配置文件名] - 重置配置文件到默认值\n\n"
        "配置文件名示例: config, cooldown, police\n"
        "配置项路径示例: base.initial_money, staff.max_work_hours\n\n"
        "注意: 所有设置功能仅机器人主人可用"
    )


# ------------------------------------------------------------ 反作弊开关 --
@cmd(r"^#开启反作弊$", name="anticheat_enable", priority=6)
async def anticheat_enable(self, event):
    """(管理员)开启反作弊系统"""
    if not _is_master(event):
        yield "只有机器人主人才能使用该功能"
        return
    await set_anti_cheat_enabled(True)
    yield "反作弊系统已开启，检测到数据不一致的用户将被封禁。"


@cmd(r"^#关闭反作弊$", name="anticheat_disable", priority=6)
async def anticheat_disable(self, event):
    """(管理员)关闭反作弊系统并清空封禁"""
    if not _is_master(event):
        yield "只有机器人主人才能使用该功能"
        return
    await set_anti_cheat_enabled(False)
    await save_ban_list({})
    yield (
        "反作弊系统已关闭，所有封禁记录已清空。"
        "当检测到数据不一致时，系统将不会封禁用户，而是继续执行功能。"
    )


@cmd(r"^#反作弊状态$", name="anticheat_status", priority=6)
async def anticheat_status(self, event):
    """查看反作弊系统状态"""
    state = "已开启" if await is_anti_cheat_enabled() else "已关闭"
    yield f"反作弊系统当前状态：{state}"


# ------------------------------------------------------------ 防作弊系统 --
@cmd(r"^#封禁用户\s+(\S+)", name="admin_ban_user", priority=6)
async def admin_ban_user(self, event):
    """(管理员)封禁用户：#封禁用户 [ID]"""
    if not _is_master(event):
        yield "只有机器人主人才能使用该功能"
        return
    import re

    match = re.match(
        r"^#封禁用户\s+(\S+)",
        event.get_message_str().strip(),
    )
    target = match.group(1) if match else ""
    if not target:
        yield "格式：#封禁用户 [用户ID]"
        return
    days = random.randint(7, 180)
    until, _days = await ban_user(target, days)
    readable = datetime.fromtimestamp(until / 1000).strftime("%Y-%m-%d %H:%M:%S")
    yield f"用户{target}已被封禁{days}天，封禁到{readable}。"


@cmd(r"^#解除封禁\s+(\S+)", name="admin_unban_user", priority=6)
async def admin_unban_user(self, event):
    """(管理员)解除封禁：#解除封禁 [ID]"""
    if not _is_master(event):
        yield "只有机器人主人才能使用该功能"
        return
    import re

    match = re.match(
        r"^#解除封禁\s+(\S+)",
        event.get_message_str().strip(),
    )
    target = match.group(1) if match else ""
    if not target:
        yield "格式：#解除封禁 [用户ID]"
        return
    if await unban_user(target):
        yield f"用户{target}已解除封禁。"
    else:
        yield f"用户{target}不在封禁列表中。"


@cmd(r"^#同步所有数据$", name="admin_sync_all", priority=6)
async def admin_sync_all(self, event):
    """(管理员)全量校验并修复所有存档"""
    if not _is_master(event):
        yield "只有机器人主人才能使用该功能"
        return
    from . import base as _guards

    total = 0
    repaired = 0
    for user_id, user_data in (await load_all_users()).items():
        total += 1
        before = dict(user_data)
        for key, value in _guards.DEFAULT_PLAYER.items():
            if key not in user_data:
                user_data[key] = value
        if user_data != before:
            from ..core.db import save_user

            await save_user(user_id, user_data)
            repaired += 1
    yield f"数据同步完成！\n共检查{total}个存档，修复{repaired}个缺失字段的存档。"


@cmd(r"^#数据同步报告$", name="admin_sync_report", priority=6)
async def admin_sync_report(self, event):
    """查看数据同步状态报告"""
    users = await load_all_users()
    bans = await load_ban_list()
    active_bans = [uid for uid, until in bans.items() if until > time.time() * 1000]
    anti_state = "已开启" if await is_anti_cheat_enabled() else "已关闭"
    yield (
        "数据同步报告\n\n"
        f"存档总数：{len(users)}\n"
        f"封禁记录：{len(active_bans)} 条有效 / {len(bans)} 条历史\n"
        f"反作弊状态：{anti_state}\n"
        f"报告时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ------------------------------------------------------------------ 更新 --
@cmd(r"^#*模拟人生(插件)?(强制)?更新$", name="plugin_update", priority=1)
async def plugin_update(self, event):
    """插件更新说明"""
    if not _is_master(event):
        yield "只有机器人主人才能执行更新操作"
        return
    forced = "强制" in event.get_message_str()
    yield (
        "AstrBot 插件更新方式：\n\n"
        "1. 打开 AstrBot WebUI → 插件管理\n"
        f"2. 找到「模拟人生 Sims」点击 {'强制更新' if forced else '更新'}\n"
        "3. 或在服务器上执行 git pull 后重载插件\n\n"
        "仓库地址：https://github.com/wbndm/astrbot_plugin_sims"
    )
