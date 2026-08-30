"""独立端口 WebUI 服务器 (aiohttp + 二次元粉樱动效风格 + 全量管理API)。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from ..core import config, db
from ..handlers import get_commands

COOKIE = "sims_session"
TTL = 12 * 3600


def _json(obj: Any, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(obj, ensure_ascii=False),
        status=status,
        content_type="application/json",
        charset="utf-8",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
    )


class SimsWebUIServer:
    def __init__(
        self,
        host: str,
        port: int,
        version: str,
        logger: Any,
        password: str = "",
        config_data: dict | None = None,
    ) -> None:
        self.host = host or "127.0.0.1"
        self.port = int(port)
        self.version = version
        self.log = logger
        self.password = str(password or "")
        self.auth_on = bool(self.password)
        self._secret = secrets.token_hex(32)
        self._config_data = config_data or {}
        self.dir = Path(__file__).parent
        self._runner: web.AppRunner | None = None

    def _token(self, exp: int) -> str:
        sig = hmac.new(
            self._secret.encode(), f"sims:{exp}".encode(), hashlib.sha256
        ).hexdigest()
        return f"{exp}.{sig}"

    def _authed(self, request: web.Request) -> bool:
        if not self.auth_on:
            return True
        raw = request.cookies.get(COOKIE, "")
        parts = raw.split(".", 1)
        if len(parts) != 2:
            return False
        try:
            exp = int(parts[0])
        except ValueError:
            return False
        if exp < time.time():
            return False
        expected = self._token(exp)
        return hmac.compare_digest(raw, expected)

    def _unauth(self) -> web.Response:
        return _json({"error": "未登录或登录已过期", "need_auth": True}, 401)

    def _file(self, fname: str, ctype: str) -> web.Response:
        p = self.dir / fname
        if not p.exists():
            return web.Response(status=404, text=f"{fname} not found")
        body = p.read_bytes()
        return web.Response(
            body=body,
            content_type=ctype,
            charset="utf-8" if ctype.startswith("text/") or "javascript" in ctype else None,
            headers={"Cache-Control": "no-cache"},
        )

    def build_app(self) -> web.Application:
        app = web.Application()
        r = app.router
        r.add_get("/", self._index)
        r.add_get("/webui/style.css", self._style_css)
        r.add_get("/webui/app.js", self._app_js)

        # 认证与元数据
        r.add_get("/api/meta", self._meta)
        r.add_post("/api/auth/login", self._login)
        r.add_post("/api/auth/logout", self._logout)
        r.add_get("/api/auth/check", self._check)

        # 仪表盘与动态
        r.add_get("/api/overview", self._overview)
        r.add_get("/api/rank", self._rank)

        # 玩家管理
        r.add_get("/api/players", self._players)
        r.add_get("/api/player", self._player_detail)
        r.add_post("/api/player/update", self._player_update)
        r.add_post("/api/player/ban", self._player_ban)
        r.add_post("/api/player/unban", self._player_unban)
        r.add_post("/api/player/delete", self._player_delete)

        # 股市与世界事件
        r.add_get("/api/stocks", self._stocks)
        r.add_post("/api/stocks/edit", self._stock_edit)
        r.add_get("/api/world/current", self._world_current)
        r.add_post("/api/world/force", self._world_force)

        # 配置管理
        r.add_get("/api/config", self._get_config)
        r.add_post("/api/config", self._save_config)
        return app

    async def start(self) -> None:
        app = self.build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------- views --
    async def _index(self, request): return self._file("index.html", "text/html")
    async def _style_css(self, request): return self._file("style.css", "text/css")
    async def _app_js(self, request): return self._file("app.js", "application/javascript")

    async def _meta(self, request):
        return _json({
            "name": "模拟人生 · 小镇物语",
            "version": self.version,
            "port": self.port,
            "auth_required": self.auth_on,
        })

    async def _login(self, request):
        body = await request.json() if request.can_read_body else {}
        pwd = str(body.get("password", ""))
        if not self.auth_on or pwd == self.password:
            exp = int(time.time() + TTL)
            token = self._token(exp)
            resp = _json({"status": "ok", "exp": exp})
            resp.set_cookie(COOKIE, token, max_age=TTL, httponly=True, path="/", samesite="Lax")
            return resp
        return _json({"error": "密码错误"}, 403)

    async def _logout(self, request):
        resp = _json({"status": "ok"})
        resp.del_cookie(COOKIE, path="/")
        return resp

    async def _check(self, request):
        return _json({"authed": self._authed(request), "auth_required": self.auth_on})

    async def _overview(self, request):
        if not self._authed(request):
            return self._unauth()
        all_u = await db.load_all_users()
        stats = await db.db.stats()
        world_event = await db.db.read_kv("world_event", None)
        return _json({
            "players": len(all_u),
            "total_money": sum(int(u.get("money", 0)) for u in all_u.values()),
            "db_size_kb": round(stats.get("db_size", 0) / 1024.0, 1),
            "commands": len(get_commands()),
            "world_event": world_event,
        })

    async def _rank(self, request):
        if not self._authed(request):
            return self._unauth()
        all_u = await db.load_all_users()
        wealth = sorted(all_u.items(), key=lambda x: -int(x[1].get("money", 0)))[:20]
        level = sorted(all_u.items(), key=lambda x: -(x[1].get("career", {}).get("level", 0) if x[1].get("career") else x[1].get("level", 1)))[:20]
        return _json({
            "wealth": [{"uid": uid, "name": u.get("name"), "value": u.get("money", 0), "career": (u.get("career") or {}).get("name", "无业")} for uid, u in wealth],
            "level": [{"uid": uid, "name": u.get("name"), "value": (u.get("career") or {}).get("level", 1), "career": (u.get("career") or {}).get("name", "居民")} for uid, u in level],
        })

    async def _players(self, request):
        if not self._authed(request):
            return self._unauth()
        users = await db.load_all_users()
        page = max(1, int(request.query.get("page", 1)))
        size = 15
        items = [
            {
                "uid": uid,
                "name": u.get("name"),
                "money": u.get("money", 0),
                "stamina": u.get("stamina", 100),
                "career": (u.get("career") or {}).get("name", "无"),
                "level": (u.get("career") or {}).get("level", 1),
            }
            for uid, u in users.items()
        ]
        start = (page - 1) * size
        return _json({
            "total": len(items),
            "page": page,
            "pages": (len(items) + size - 1) // size or 1,
            "items": items[start:start + size],
        })

    async def _player_detail(self, request):
        if not self._authed(request):
            return self._unauth()
        uid = request.query.get("uid", "").strip()
        data = await db.check_user(uid)
        if not data:
            return _json({"error": "玩家不存在"}, 404)
        return _json({"uid": uid, "data": data})

    async def _player_update(self, request):
        if not self._authed(request):
            return self._unauth()
        body = await request.json() if request.can_read_body else {}
        uid = str(body.get("uid", "")).strip()
        fields = body.get("fields") or {}
        data = await db.check_user(uid)
        if not data:
            return _json({"error": "玩家不存在"}, 404)
        for k, v in fields.items():
            if k in {"money", "stamina", "happiness", "health", "charm", "level"}:
                data[k] = int(v)
            elif k in {"name", "signature", "gender"}:
                data[k] = str(v)
        await db.save_user(uid, data)
        return _json({"status": "ok", "updated": data})

    async def _player_ban(self, request):
        if not self._authed(request):
            return self._unauth()
        body = await request.json() if request.can_read_body else {}
        uid = str(body.get("uid", "")).strip()
        bans = await db.db.read_kv("ban_list", {}) or {}
        days = int(body.get("days", 7))
        bans[uid] = int(time.time() * 1000) + days * 86400 * 1000
        await db.db.write_kv("ban_list", bans)
        return _json({"status": "ok", "banned": uid, "until": bans[uid]})

    async def _player_unban(self, request):
        if not self._authed(request):
            return self._unauth()
        body = await request.json() if request.can_read_body else {}
        uid = str(body.get("uid", "")).strip()
        bans = await db.db.read_kv("ban_list", {}) or {}
        bans.pop(uid, None)
        await db.db.write_kv("ban_list", bans)
        return _json({"status": "ok", "unbanned": uid})

    async def _player_delete(self, request):
        if not self._authed(request):
            return self._unauth()
        body = await request.json() if request.can_read_body else {}
        uid = str(body.get("uid", "")).strip()
        ok = await db.delete_user(uid)
        return _json({"status": "ok", "deleted": ok})

    async def _stocks(self, request):
        if not self._authed(request):
            return self._unauth()
        from ..core.systems.stocks import load_stock_market
        market = await load_stock_market()
        return _json(market)

    async def _stock_edit(self, request):
        if not self._authed(request):
            return self._unauth()
        body = await request.json() if request.can_read_body else {}
        sid = str(body.get("id", "")).strip()
        price = float(body.get("price", 0))
        from ..core.systems.stocks import load_stock_market, save_stock_market
        market = await load_stock_market()
        for s in market.get("stocks", []):
            if s.get("id") == sid:
                s["price"] = round(price, 2)
                break
        await save_stock_market(market)
        return _json({"status": "ok", "stocks": market.get("stocks")})

    async def _world_current(self, request):
        if not self._authed(request):
            return self._unauth()
        ev = await db.db.read_kv("world_event", None)
        return _json({"event": ev})

    async def _world_force(self, request):
        if not self._authed(request):
            return self._unauth()
        from ..core.systems.world import check_world_event_tick
        await check_world_event_tick(None)
        ev = await db.db.read_kv("world_event", None)
        return _json({"status": "ok", "event": ev})

    async def _get_config(self, request):
        if not self._authed(request):
            return self._unauth()
        return _json(config.get_config())

    async def _save_config(self, request):
        if not self._authed(request):
            return self._unauth()
        body = await request.json() if request.can_read_body else {}
        cfg = config.get_config()
        cfg.update(body)
        config.set_config(cfg)
        return _json({"status": "ok", "config": cfg})
