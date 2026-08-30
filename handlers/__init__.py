"""全部 Handlers 统一加载与导出。"""

from __future__ import annotations

import importlib
from pathlib import Path

from . import base
from .base import COMMAND_REGISTRY, get_commands

# 动态加载当前目录下所有指令模块
_DIR = Path(__file__).parent
for _py in sorted(_DIR.glob("*.py")):
    if _py.name.startswith("_") or _py.name == "base.py":
        continue
    importlib.import_module(f".{_py.stem}", package=__name__)

__all__ = ["COMMAND_REGISTRY", "base", "get_commands"]
