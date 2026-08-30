"""公告系统 - port of ``apps/announcement.js``.

Version announcement image, current-version info and text changelog.
(``#模拟人生版本`` is registered by :mod:`.help` with the image renderer;
this module intentionally does not duplicate it.)
"""

from __future__ import annotations

from ..core import gamedata
from ..core.renderer import renderer
from .base import cmd


def load_version_info() -> dict:
    data = gamedata.load_data("core/changelog.json") or {}
    return {
        "version": "1.0.0",
        "currentVersion": "1.0.0",
        "changelogs": data.get("changelogs") or [],
        "author": "wbndm",
    }


@cmd(r"^#模拟人生公告$", name="announcement_show", priority=6)
async def announcement_show(self, event):
    """查看最新版本图文公告"""
    info = load_version_info()
    changelogs = info["changelogs"]
    total_features = sum(
        len(log.get("logs") or [])
        for version in changelogs
        for log in version.get("logs") or []
    )
    total_fixes = sum(
        len(log.get("logs") or [])
        for version in changelogs
        if version.get("type") == "patch"
        for log in version.get("logs") or []
    )
    try:
        path = await renderer.render_image(
            "announcement",
            {
                "currentVersion": info["version"],
                "lastUpdate": "",
                "changelogs": changelogs,
                "totalVersions": len(changelogs),
                "totalFeatures": total_features,
                "totalFixes": total_fixes,
            },
        )
        yield event.image_result(path)
    except Exception:
        yield _text_announcement(info)


def _text_announcement(info: dict) -> str:
    changelogs = info["changelogs"]
    if not changelogs:
        return "获取公告失败，请稍后再试"
    latest = changelogs[0]
    lines = [
        f"🎮 模拟人生 v{info['version']} 公告\n",
        "━━━━━━━━━━━━━━━\n",
        f"📅 {latest.get('date', '')} | {latest.get('title', '')}\n",
    ]
    for log in latest.get("logs") or []:
        lines.append(f"{log.get('title', '')}\n")
        for detail in log.get("logs") or []:
            lines.append(f"  • {detail}\n")
        lines.append("\n")
    lines.append("━━━━━━━━━━━━━━━\n")
    lines.append("使用 #模拟人生更新日志 查看历史版本")
    return "".join(lines)


@cmd(r"^#模拟人生更新日志$", name="announcement_changelog", priority=6)
async def announcement_changelog(self, event):
    """查看历史更新日志"""
    info = load_version_info()
    changelogs = info["changelogs"]
    text = "📋 模拟人生更新日志\n━━━━━━━━━━━━━━━\n\n"
    type_emoji = {"major": "🔴", "minor": "🟢", "patch": "🟡"}
    for version in changelogs[:5]:
        emoji = type_emoji.get(version.get("type"), "⚪")
        text += f"{emoji} v{version['version']} - {version.get('title', '')}\n"
        text += f"   日期: {version.get('date', '')}\n"
        for log in version.get("logs") or []:
            text += f"   {log.get('title', '')}\n"
            for detail in log.get("logs") or []:
                text += f"     • {detail}\n"
        text += "\n"
    if len(changelogs) > 5:
        text += f"... 共{len(changelogs)}个版本\n"
    text += "━━━━━━━━━━━━━━━\n使用 #模拟人生公告 查看图文版本"
    yield text
