"""模拟人生 Sims - AstrBot 插件主入口 (继承 Star，全异步架构)。"""

from __future__ import annotations

import asyncio

from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .core import config, cron, db, renderer
from .handlers import get_commands


class SimsStar(Star):
    def __init__(self, context: Context, plugin_config: dict | None = None) -> None:
        super().__init__(context)
        self.config = plugin_config or {}
        config.set_config(self.config)
        self._hourly_task: asyncio.Task | None = None
        self._webui = None

    async def initialize(self) -> None:
        config.set_config(self.config)
        await self._start_webui()
        if not self.config.get("hourly_cron", True):
            return

        self._hourly_task = asyncio.create_task(self._hourly_loop())
        await cron.run_hourly_tick(self.context)

    async def _start_webui(self) -> None:
        if not self.config.get("webui_enabled", True):
            return
        from astrbot.api import logger

        from .webui.server import SimsWebUIServer

        host = str(self.config.get("webui_host", "127.0.0.1"))
        port = int(self.config.get("webui_port", 17818))
        password = str(self.config.get("webui_password", ""))
        self._webui = SimsWebUIServer(
            host=host,
            port=port,
            version="1.0.0",
            logger=logger,
            password=password,
            config_data=self.config,
        )
        try:
            await self._webui.start()
            logger.info(f"[模拟人生] WebUI 已启动：http://{host}:{port}")
        except Exception as e:
            logger.error(f"[模拟人生] WebUI 启动失败：{e}")
            self._webui = None

    async def terminate(self) -> None:
        if self._hourly_task:
            self._hourly_task.cancel()
            try:
                await self._hourly_task
            except asyncio.CancelledError:
                pass
            self._hourly_task = None
        if self._webui:
            await self._webui.stop()
            self._webui = None
        await renderer.renderer.shutdown()
        await db.db.close()

    async def _hourly_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await cron.run_hourly_tick(self.context)
            except Exception:
                pass

    @staticmethod
    def _register_commands() -> None:
        main_module = __name__
        for spec in get_commands():
            fn = spec["func"]
            unique_name = f"sims_{spec['name']}"
            wrapper = _wrap_handler(fn, spec)
            wrapper.__name__ = unique_name
            wrapper.__qualname__ = f"SimsStar.{unique_name}"
            wrapper.__module__ = main_module
            wrapper.__doc__ = spec["desc"] or wrapper.__doc__
            setattr(SimsStar, unique_name, wrapper)
            filter.regex(spec["pattern"], priority=spec["priority"])(wrapper)


def _wrap_handler(fn, spec):
    async def wrapper(self, event, *args, **kwargs):
        event.should_call_llm(False)
        try:
            results = fn(self, event, *args, **kwargs)
            if hasattr(results, "__aiter__"):
                async for item in results:
                    async for out in _emit(event, item):
                        yield out
            else:
                item = await results
                if item is not None:
                    async for out in _emit(event, item):
                        yield out
        except Exception as err:
            from .core.context import CommandError
            if isinstance(err, CommandError):
                async for out in _emit(event, str(err)):
                    yield out
            else:
                import traceback

                from astrbot.api import logger
                logger.error(f"[sims] {spec['name']} 执行出错:\n{traceback.format_exc()}")
                async for out in _emit(event, "指令执行出错了，请稍后再试或联系管理员。"):
                    yield out
        event.stop_event()

    return wrapper


async def _emit(event, item):
    if item is None:
        return
    if isinstance(item, str):
        from .core.config import reply_mode
        from .core.context import format_markdown, quick_hints

        platform = ""
        try:
            platform = event.get_platform_name()
        except Exception:
            pass

        if platform in {"qq_official", "qq_official_webhook"} and reply_mode() in {"auto", "text"}:
            formatted = format_markdown(item)
            hints = quick_hints(item)
            if hints:
                formatted += "\n\n**快捷指令**\n" + " | ".join(hints)
            result = event.make_result().message(formatted)
            result.use_markdown(True)
            yield result
            return

        if reply_mode() == "image":
            try:
                import time
                path = await renderer.renderer.render_image(
                    "reply",
                    {
                        "title": "模拟人生",
                        "lines": [line for line in item.split("\n")],
                        "hints": [],
                    },
                    {"filename": f"reply_{int(time.time() * 1000)}"},
                )
                if path:
                    yield event.image_result(path)
                    return
            except Exception:
                pass
        yield event.plain_result(item)
        return

    yield item


SimsStar._register_commands()
