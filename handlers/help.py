"""帮助与版本信息指令（使用 resources/texts/help.json）。"""

from __future__ import annotations

from ..core import gamedata, renderer
from .base import cmd


@cmd(r"^#模拟人生帮助$", name="help_menu", priority=1)
async def help_menu(self, event):
    """查看模拟人生游戏帮助菜单"""
    help_data = gamedata.load_text("help") or {}
    path = await renderer.renderer.render_image(
        "help/index",
        {
            "helpData": help_data,
            "title": help_data.get("title", "模拟人生 Sims"),
            "groups": help_data.get("groups", []),
        },
    )
    yield event.image_result(path)


@cmd(r"^#模拟人生版本$", name="version_info", priority=1)
async def version_info(self, event):
    """查看模拟人生版本与更新日志"""
    changelog = gamedata.load_data("core/changelog.json") or {}
    path = await renderer.renderer.render_image(
        "help/version-info",
        {
            "version": "1.0.0",
            "changelog": changelog,
        },
    )
    yield event.image_result(path)
