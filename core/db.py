"""全异步 SQLite 存储引擎 (aiosqlite + WAL + 并发双重锁)。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable

import aiosqlite


def _default_root() -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        return Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_sims"
    except Exception:
        return Path(__file__).resolve().parent.parent / "resources" / "data" / "_runtime"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id       TEXT PRIMARY KEY,
    data          TEXT NOT NULL,
    last_modified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class AsyncStore:
    """全异步玩家存档与全局 KV 存储。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else _default_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "sims.db"
        self._lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            async with self._lock:
                if self._conn is None:
                    self._conn = await aiosqlite.connect(str(self.db_path), timeout=30.0)
                    await self._conn.execute("PRAGMA journal_mode=WAL")
                    await self._conn.execute("PRAGMA synchronous=NORMAL")
                    await self._conn.execute("PRAGMA busy_timeout=30000")
                    await self._conn.executescript(_SCHEMA)
                    await self._conn.commit()
        return self._conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                try:
                    await self._conn.commit()
                except Exception:
                    pass
                await self._conn.close()
                self._conn = None

    # ------------------------------------------------------------- users --
    async def check_user(self, user_id: str) -> dict[str, Any] | None:
        """异步加载玩家存档；不存在时返回 None。"""
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute(
                "SELECT data FROM players WHERE user_id = ?",
                (str(user_id),),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def save_user(self, user_id: str, data: dict[str, Any]) -> None:
        """异步持久化玩家存档。"""
        data["_lastModified"] = int(time.time() * 1000)
        payload = json.dumps(data, ensure_ascii=False)
        modified = data["_lastModified"]
        conn = await self._get_conn()
        async with self._lock:
            await conn.execute(
                "INSERT INTO players(user_id, data, last_modified) VALUES(?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, "
                "last_modified=excluded.last_modified",
                (str(user_id), payload, modified),
            )
            await conn.commit()

    async def delete_user(self, user_id: str) -> bool:
        """异步删除玩家档案。"""
        conn = await self._get_conn()
        async with self._lock:
            cursor = await conn.execute(
                "DELETE FROM players WHERE user_id = ?",
                (str(user_id),),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def load_all_users(self) -> dict[str, dict[str, Any]]:
        """异步加载所有玩家档案。"""
        conn = await self._get_conn()
        users: dict[str, dict[str, Any]] = {}
        async with self._lock:
            async with conn.execute("SELECT user_id, data FROM players") as cursor:
                rows = await cursor.fetchall()
        for user_id, payload in rows:
            try:
                data = json.loads(payload)
                if isinstance(data, dict):
                    users[str(user_id)] = data
            except Exception:
                continue
        return users

    # ----------------------------------------------------------------- kv --
    async def read_kv(self, name: str, default: Any = None) -> Any:
        """异步读取 KV 文档。"""
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute(
                "SELECT value FROM kv WHERE key = ?",
                (str(name),),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return default

    async def write_kv(self, name: str, value: Any) -> None:
        """异步写入 KV 文档。"""
        payload = json.dumps(value, ensure_ascii=False)
        conn = await self._get_conn()
        async with self._lock:
            await conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(name), payload),
            )
            await conn.commit()

    async def update_kv(
        self,
        name: str,
        mutator: Callable[[Any], Any],
        default: Any = None,
    ) -> Any:
        """异步原子修改 KV 文档。"""
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute(
                "SELECT value FROM kv WHERE key = ?",
                (str(name),),
            ) as cursor:
                row = await cursor.fetchone()
            current = default
            if row:
                try:
                    current = json.loads(row[0])
                except Exception:
                    current = default
            res = mutator(current)
            final_val = res if res is not None else current
            payload = json.dumps(final_val, ensure_ascii=False)
            await conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(name), payload),
            )
            await conn.commit()
            return final_val

    async def read_all_kv(self) -> dict[str, Any]:
        """异步读取全量 KV。"""
        conn = await self._get_conn()
        result: dict[str, Any] = {}
        async with self._lock:
            async with conn.execute("SELECT key, value FROM kv") as cursor:
                rows = await cursor.fetchall()
        for key, payload in rows:
            try:
                result[str(key)] = json.loads(payload)
            except Exception:
                continue
        return result

    async def wipe(self) -> None:
        """清空全库数据。"""
        conn = await self._get_conn()
        async with self._lock:
            await conn.execute("DELETE FROM players")
            await conn.execute("DELETE FROM kv")
            await conn.commit()

    async def stats(self) -> dict[str, Any]:
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute("SELECT COUNT(*) FROM players") as cur:
                players = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM kv") as cur:
                kv_count = (await cur.fetchone())[0]
        size = (await asyncio.to_thread(lambda: self.db_path.stat().st_size)) if self.db_path.exists() else 0
        return {"players": players, "kv": kv_count, "db_size": size}


# 全局单例
db = AsyncStore()


def get_db() -> AsyncStore:
    return db


# 快捷函数
# 兼容历史别名
Store = AsyncStore
store = db


def get_store() -> AsyncStore:
    return db


async def check_user(user_id: str) -> dict[str, Any] | None:
    return await db.check_user(user_id)


async def save_user(user_id: str, data: dict[str, Any]) -> None:
    await db.save_user(user_id, data)


async def delete_user(user_id: str) -> bool:
    return await db.delete_user(user_id)


async def load_all_users() -> dict[str, dict[str, Any]]:
    return await db.load_all_users()


async def load_ban_list() -> dict[str, int]:
    return await db.read_kv("ban_list", {}) or {}


async def save_ban_list(bans: dict[str, int]) -> None:
    await db.write_kv("ban_list", bans)


async def get_ban_until(user_id: str) -> int | None:
    bans = await load_ban_list()
    until = bans.get(str(user_id))
    if until is None:
        return None
    if until <= int(time.time() * 1000):
        bans.pop(str(user_id), None)
        await save_ban_list(bans)
        return None
    return until


async def check_banned(user_id: str) -> int | None:
    return await get_ban_until(user_id)


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


async def get_achievements(user_id: str) -> list[dict]:
    data = await db.read_kv(f"achievements_{user_id}", [])
    return data if isinstance(data, list) else []


async def save_achievement(user_id: str, ach: dict) -> bool:
    def _mutate(state):
        unlocked = state.setdefault("unlocked", [])
        if ach["id"] not in unlocked:
            unlocked.append(ach["id"])
            state.setdefault("times", {})[ach["id"]] = int(time.time() * 1000)
            return state
        return state

    await db.update_kv(f"achievement_state_{user_id}", _mutate, {"unlocked": [], "times": {}})
    return True

