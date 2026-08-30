"""6大职业体系、技能晋升、跨玩家协作与联动任务链。"""

from __future__ import annotations

import time
from typing import Any

from ..db import db

COLLAB_KV = "careers_collab"


async def load_collab() -> dict[str, Any]:
    data = await db.read_kv(COLLAB_KV, None)
    if isinstance(data, dict):
        data.setdefault("pairs", {})
        data.setdefault("invites", {})
        data.setdefault("stats", {})
        data.setdefault("chains", {})
        return data
    initial = {"pairs": {}, "invites": {}, "stats": {}, "chains": {}}
    await db.write_kv(COLLAB_KV, initial)
    return initial


async def save_collab(data: dict) -> None:
    await db.write_kv(COLLAB_KV, data)


def clean_expired(collab: dict) -> None:
    now = time.time()
    collab["invites"] = {
        k: v for k, v in collab.get("invites", {}).items()
        if (now - v.get("time", 0)) < 300
    }
