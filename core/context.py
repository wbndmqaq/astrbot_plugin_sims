"""运行时上下文与冷却管理。"""

from __future__ import annotations

import random as _random
import re
import time
from typing import Any

from . import config

_cooldowns: dict[str, int] = {}
_last_cleanup = 0.0


class CommandError(Exception):
    """业务逻辑中断并友好提示异常。"""


def rnd(minimum: int, maximum: int) -> int:
    """包含边界的随机整数。"""
    return _random.randint(int(minimum), int(maximum))


def _cleanup() -> None:
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 3600:
        return
    _last_cleanup = now
    expired = [k for k, v in _cooldowns.items() if v < now * 1000]
    for key in expired:
        _cooldowns.pop(key, None)


def get_cd_ms(category: str, cd_type: str) -> int:
    """获取冷却时间（毫秒）。支持在 _conf_schema 配置中自定义。"""
    cfg_val = config.get(f"cd_{category}_{cd_type}") or config.get(f"cd_{category}")
    if cfg_val is not None:
        try:
            return max(0, int(cfg_val)) * 1000
        except (TypeError, ValueError):
            pass
    # 默认 60 秒
    return 60_000


def cd_remaining(user_id: str, category: str, cd_type: str) -> int:
    """查询剩余冷却秒数，0 为可执行。"""
    _cleanup()
    key = f"{user_id}-{category}-{cd_type}"
    until = _cooldowns.get(key)
    if until is None:
        return 0
    remaining_ms = until - int(time.time() * 1000)
    return max(0, -(-remaining_ms // 1000))


def set_cd(user_id: str, category: str, cd_type: str) -> None:
    """设定用户指令冷却。"""
    key = f"{user_id}-{category}-{cd_type}"
    _cooldowns[key] = int(time.time() * 1000) + get_cd_ms(category, cd_type)


def reset_user_cds(user_id: str) -> None:
    """重置指定用户的所有冷却。"""
    prefix = f"{user_id}-"
    for key in [k for k in _cooldowns if k.startswith(prefix)]:
        _cooldowns.pop(key, None)


def raw_msg(event: Any) -> str:
    try:
        return (event.get_message_str() or "").strip()
    except Exception:
        return ""


def arg_after(event: Any, *prefixes: str) -> str:
    """提取去除命令前缀后的参数文本。"""
    msg = raw_msg(event)
    for prefix in sorted(prefixes, key=len, reverse=True):
        pattern = rf"^#?\s*{re.escape(prefix.lstrip('#'))}\s*"
        rest = re.sub(pattern, "", msg, count=1)
        if rest != msg or msg.lower().startswith(prefix.lower()):
            return rest.strip()
    return msg.strip()


def sender_id(event: Any) -> str:
    return str(event.get_sender_id())


def format_markdown(text: str, title_max: int = 15) -> str:
    """QQ 官方 Markdown 排版格式化。"""
    def _is_divider(line: str) -> bool:
        return bool(re.match(r"^[-─━═=_~*·]{3,}$", line))

    out: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if re.match(r"^【[^\n【】]+】$", line):
            if out and out[-1] != "":
                out.append("")
            out.append(f"**{line}**")
            out.append("")
            continue
        if _is_divider(line):
            prev = out[-1].strip() if out else ""
            if (
                prev
                and not prev.startswith("**")
                and len(prev) <= title_max
                and not re.search(r"[:：#0-9a-zA-Z]", prev)
                and not _is_divider(prev)
            ):
                out[-1] = f"**{prev}**"
                out.append("")
                continue
            if out and out[-1] == "---":
                continue
            if prev and out[-1] != "":
                out.append("")
            out.append("---")
            out.append("")
            continue
        out.append(raw_line)
    result = "\n".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def quick_hints(text: str) -> list[str]:
    """提取文本中的 # 指令作为快捷入口。"""
    hints: list[str] = []
    for token in re.findall(r"#[\w\u4e00-\u9fff]{2,12}", text):
        if token not in hints:
            hints.append(token)
        if len(hints) >= 6:
            break
    return hints
