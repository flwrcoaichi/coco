from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from aiohttp import web
from discord import ui

from src.cogs.messages.db import (
    delete_message,
    get_message,
    list_messages,
    set_posted,
    upsert_message,
)
from src.cogs.messages.layout import compose_message
from src.cogs.ticketing.cog import OpenTicketButton
from src.cogs.ticketing.db import create_panel, get_ticket_panels, set_panel_message
from src.data.button_containers import (
    delete_container,
    get_container,
    get_containers,
    save_container,
)
from src.data.config import (
    delete_config,
    get_all_config,
    get_moderation_config,
    set_config,
    set_moderation_config,
)
from src.utils.logger import get_logger
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("web.server")

_DISCORD_API = "https://discord.com/api/v10"
_ADMIN_BIT = 0x8
_SESSION_TTL = 60.0
_JS_SAFE_INT = 2**53


def _auth_header(request: web.Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip() or None


def _is_admin_guild(guild_data: dict[str, Any]) -> bool:
    raw = str(guild_data.get("permissions", "0"))
    try:
        return bool(int(raw) & _ADMIN_BIT) or bool(guild_data.get("owner", False))
    except ValueError:
        return bool(guild_data.get("owner", False))


def _safe(obj: Any) -> Any:
    """snowflakes exceed JS's 2^53 integer limit and get silently rounded by
    JSON.parse - send them as strings."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int) and abs(obj) >= _JS_SAFE_INT:
        return str(obj)
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe(v) for v in obj]
    return obj


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(_safe(data), status=status)


def _err(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


class DashboardServer:
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self.config = bot.config
        self.app = web.Application()
        self.app["bot"] = bot
        self.app["session"] = None
        self.origin = self.config.dashboard_origin
        self._runner: web.AppRunner | None = None
        self._auth_cache: dict[str, dict[str, Any]] = {}
        self._auth_locks: dict[str, asyncio.Lock] = {}

        self.app.on_startup.append(self._on_startup)
        self.app.on_cleanup.append(self._on_cleanup)
        self.app.middlewares.append(self._cors_middleware)

        self._register_routes()

    async def _on_startup(self, app: web.Application) -> None:
        app["session"] = aiohttp.ClientSession()

    async def _on_cleanup(self, app: web.Application) -> None:
        session: aiohttp.ClientSession | None = app.get("session")
        if session is not None and not session.closed:
            await session.close()

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler: web.Handler) -> web.StreamResponse:
        if request.method == "OPTIONS":
            response: web.StreamResponse = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except web.HTTPException as exc:
                response = exc

        req_origin = request.headers.get("Origin", self.origin)
        if "://" in req_origin:
            scheme, host = req_origin.split("://", 1)
            clean_origin = f"{scheme}://{host.split('/')[0]}"
        else:
            clean_origin = req_origin

        response.headers.update(
            {
                "Access-Control-Allow-Origin": clean_origin,
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Credentials": "true",
            }
        )
        return response

    def _register_routes(self) -> None:
        prefix = "/niska"
        self.app.router.add_get(prefix, self._serve_index)
        self.app.router.add_get(f"{prefix}/", self._serve_index)
        self.app.router.add_get(f"{prefix}/dashboard", self._serve_dashboard)
        self.app.router.add_get(f"{prefix}/docs", self._serve_docs)
        self.app.router.add_get(f"{prefix}/static/{{filename}}", self._serve_static)
        routes = (
            ("GET", "/api/config", self._handle_public_config),
            ("GET", "/api/guilds", self._handle_guilds),
            ("GET", "/api/guild/{guild_id}/config", self._handle_get_config),
            ("POST", "/api/guild/{guild_id}/config", self._handle_set_config),
            ("GET", "/api/guild/{guild_id}/moderation", self._handle_get_moderation),
            ("POST", "/api/guild/{guild_id}/moderation", self._handle_set_moderation),
            ("GET", "/api/guild/{guild_id}/channels", self._handle_get_channels),
            ("GET", "/api/guild/{guild_id}/roles", self._handle_get_roles),
            ("GET", "/api/guild/{guild_id}/ticket_panels", self._handle_get_ticket_panels),
            ("POST", "/api/guild/{guild_id}/ticket_panels", self._handle_create_ticket_panel),
            ("GET", "/api/guild/{guild_id}/containers", self._handle_get_containers),
            ("POST", "/api/guild/{guild_id}/containers", self._handle_save_container),
            ("DELETE", "/api/guild/{guild_id}/containers/{name}", self._handle_delete_container),
            ("GET", "/api/guild/{guild_id}/state", self._handle_get_state),
            ("POST", "/api/guild/{guild_id}/actions/{action}", self._handle_action),
            ("GET", "/api/guild/{guild_id}/messages", self._handle_list_messages),
            ("POST", "/api/guild/{guild_id}/messages", self._handle_save_message),
            ("POST", "/api/guild/{guild_id}/messages/{name}/send", self._handle_send_message),
            ("PUT", "/api/guild/{guild_id}/messages/{name}", self._handle_update_message),
            ("DELETE", "/api/guild/{guild_id}/messages/{name}", self._handle_delete_message),
        )
        for method, path, handler in routes:
            self.app.router.add_route(method, f"{prefix}{path}", handler)

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.dashboard_host, self.config.dashboard_port)
        await site.start()
        log.info("dashboard available at http://%s:%s", self.config.dashboard_host, self.config.dashboard_port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _discord_get(self, path: str, token: str) -> tuple[int, Any]:
        session: aiohttp.ClientSession = self.app["session"]
        for attempt in range(3):
            async with session.get(
                f"{_DISCORD_API}{path}", headers={"Authorization": f"Bearer {token}"}
            ) as resp:
                if resp.status == 429 and attempt < 2:
                    try:
                        wait = float((await resp.json()).get("retry_after", 1))
                    except Exception:
                        wait = 1.0
                    await asyncio.sleep(min(wait, 5))
                    continue
                body = await resp.json() if resp.status == 200 else None
                return resp.status, body
        return 429, None

    def _prune_cache(self) -> None:
        now = time.monotonic()
        for token in [t for t, v in self._auth_cache.items() if v["exp"] <= now]:
            self._auth_cache.pop(token, None)
        for token in [t for t, lock in self._auth_locks.items() if t not in self._auth_cache and not lock.locked()]:
            self._auth_locks.pop(token, None)

    async def _session_info(self, token: str) -> dict[str, Any] | web.Response:
        cached = self._auth_cache.get(token)
        if cached and cached["exp"] > time.monotonic():
            return cached
        lock = self._auth_locks.setdefault(token, asyncio.Lock())
        async with lock:
            cached = self._auth_cache.get(token)
            if cached and cached["exp"] > time.monotonic():
                return cached
            (user_status, user), (guilds_status, guilds) = await asyncio.gather(
                self._discord_get("/users/@me", token),
                self._discord_get("/users/@me/guilds", token),
            )
            if user_status == 401 or guilds_status == 401:
                self._auth_cache.pop(token, None)
                return _err("unauthorized", 401)
            if user_status != 200 or guilds_status != 200 or not isinstance(guilds, list):
                log.warning("discord lookup failed (user=%s guilds=%s)", user_status, guilds_status)
                return _err("discord is rate limiting or unavailable, try again shortly", 503)
            info = {
                "user_id": str(user.get("id", "")),
                "guilds": {str(g.get("id")): g for g in guilds},
                "exp": time.monotonic() + _SESSION_TTL,
            }
            self._auth_cache[token] = info
            if len(self._auth_cache) > 256:
                self._prune_cache()
            return info

    async def _user(self, request: web.Request) -> dict[str, Any] | web.Response:
        token = _auth_header(request)
        if not token:
            return _err("unauthorized", 401)
        return await self._session_info(token)

    async def _guild(self, request: web.Request) -> tuple[int, int, discord.Guild] | web.Response:
        info = await self._user(request)
        if isinstance(info, web.Response):
            return info
        try:
            guild_id = int(request.match_info["guild_id"])
        except (KeyError, ValueError):
            return _err("bad guild id", 400)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return _err("guild not found", 404)
        if info["user_id"] != str(guild.owner_id):
            data = info["guilds"].get(str(guild_id))
            if data is None or not _is_admin_guild(data):
                return _err("forbidden", 403)
        return guild_id, int(info["user_id"]), guild

    async def _handle_public_config(self, request: web.Request) -> web.Response:
        return _json({"discord_client_id": self.config.discord_client_id})

    async def _handle_guilds(self, request: web.Request) -> web.Response:
        info = await self._user(request)
        if isinstance(info, web.Response):
            return info
        bot_guilds = {str(g.id) for g in self.bot.guilds}
        out = [
            {"id": gid, "name": str(g.get("name", "")), "icon": g.get("icon")}
            for gid, g in info["guilds"].items()
            if gid in bot_guilds and _is_admin_guild(g)
        ]
        return _json(out)

    async def _handle_get_config(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        return _json(await get_all_config(self.bot.db, auth[0]))

    async def _handle_set_config(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        payload = await request.json()
        for key, value in payload.items():
            if value is None or value == "":
                await delete_config(self.bot.db, auth[0], key)
            else:
                await set_config(self.bot.db, auth[0], key, value)
        return _json({"ok": True})

    async def _handle_get_moderation(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        return _json(await get_moderation_config(self.bot.db, auth[0]))

    async def _handle_set_moderation(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        await set_moderation_config(self.bot.db, auth[0], await request.json())
        return _json({"ok": True})

    async def _handle_get_channels(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        channels = []
        for channel in auth[2].channels:
            if isinstance(channel, discord.TextChannel):
                channels.append({"id": str(channel.id), "name": channel.name, "type": "text"})
            elif isinstance(channel, discord.CategoryChannel):
                channels.append({"id": str(channel.id), "name": channel.name, "type": "category"})
        return _json(channels)

    async def _handle_get_roles(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        roles = [
            {
                "id": str(role.id),
                "name": role.name,
                "color": f"#{role.color.value:06x}" if role.color.value else "#99aab5",
            }
            for role in reversed(auth[2].roles)
            if not role.is_default() and not role.managed
        ]
        return _json(roles)

    async def _handle_get_state(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        queue_cog = self.bot.get_cog("queue")
        if queue_cog is None:
            return _err("queue missing", 500)
        return _json({"ok": True, "state": queue_cog.get_state(auth[0])})  # type: ignore[attr-defined]

    async def _handle_action(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        guild_id, _, guild = auth
        action = request.match_info["action"]
        payload = await request.json()
        queue_cog = self.bot.get_cog("queue")
        music_cog = self.bot.get_cog("music")

        if action == "play":
            url = str(payload.get("url", "")).strip()
            if not url:
                return _err("missing url", 400)
            if music_cog is None:
                return _err("music disabled", 500)
            voice_channel_id = int(payload.get("voice_channel_id", 0) or 0)
            voice_channel = guild.get_channel(voice_channel_id) if voice_channel_id else None
            ok, message = await music_cog.queue_from_url(  # type: ignore[attr-defined]
                guild_id, url, voice_channel if isinstance(voice_channel, discord.VoiceChannel) else None
            )
            return _json({"ok": ok, "message": message})

        vc = guild.voice_client
        if action == "pause":
            if not isinstance(vc, discord.VoiceClient):
                return _err("not connected", 400)
            if not vc.is_playing():
                return _err("not playing", 400)
            vc.pause()
            return _json({"ok": True, "message": "paused"})

        if action == "resume":
            if not isinstance(vc, discord.VoiceClient):
                return _err("not connected", 400)
            if not vc.is_paused():
                return _err("not paused", 400)
            vc.resume()
            return _json({"ok": True, "message": "resumed"})

        if action in {"skip", "stop"}:
            if queue_cog is None:
                return _err("queue missing", 500)
            if action == "skip":
                if not isinstance(vc, discord.VoiceClient) or not vc.is_playing():
                    return _err("not playing", 400)
                queue_cog.skip(guild_id, vc)  # type: ignore[attr-defined]
                return _json({"ok": True, "message": "skipped"})
            queue_cog.clear(guild_id)  # type: ignore[attr-defined]
            if isinstance(vc, discord.VoiceClient):
                await vc.disconnect(force=True)
            return _json({"ok": True, "message": "stopped"})

        return _err("unknown action", 400)

    async def _handle_get_ticket_panels(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        return _json(await get_ticket_panels(self.bot.db, auth[0]))

    async def _handle_create_ticket_panel(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        guild_id, _, guild = auth
        payload = await request.json()
        channel_id = int(payload.get("channel_id") or 0)
        if channel_id <= 0:
            return _err("missing channel_id", 400)
        title = str(payload.get("title", "support")).strip() or "support"
        description = str(payload.get("description", "")).strip() or "click below to open a ticket"
        category_id = int(payload.get("category_id") or 0)
        staff_role_id = int(payload.get("staff_role_id") or 0)

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return _err("channel not found or not a text channel", 404)

        panel_id = await create_panel(
            self.bot.db, guild_id, channel_id, category_id, staff_role_id, title, description
        )
        layout = BaseLayout()
        layout.add_container(ui.TextDisplay(f"# {title}\n{description}"), accent_color=0x5865F2)
        layout.add_item(ui.ActionRow(OpenTicketButton(panel_id)))
        try:
            msg = await channel.send(view=layout)
        except discord.HTTPException as exc:
            return _err(f"failed to send ticket panel message: {exc}", 500)

        await set_panel_message(self.bot.db, panel_id, msg.id)
        return _json({"ok": True, "panel_id": panel_id, "message_id": msg.id})

    async def _handle_get_containers(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        return _json(await get_containers(self.bot.db, auth[0]))

    async def _handle_save_container(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        body = await request.json()
        name = str(body.get("name", "")).strip()
        items = body.get("items")
        accent_color = body.get("accent_color")
        if not name:
            return _err("missing container name", 400)
        if not isinstance(items, list):
            return _err("items must be a list", 400)
        try:
            accent_color = int(accent_color) if accent_color is not None else None
        except (TypeError, ValueError):
            accent_color = None
        await save_container(self.bot.db, auth[0], name, auth[1], items, accent_color)
        return _json({"ok": True})

    async def _handle_delete_container(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        await delete_container(self.bot.db, auth[0], request.match_info["name"])
        return _json({"ok": True})

    async def _handle_list_messages(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        msgs = await list_messages(self.bot.db, auth[0])
        containers = {c["name"]: c for c in await get_containers(self.bot.db, auth[0])}
        for m in msgs:
            c = containers.get(m["container_name"]) if m["container_name"] else None
            m["items"] = c["items"] if c else []
            m["accent_color"] = c["accent_color"] if c else None
        return _json(msgs)

    async def _handle_save_message(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        payload = await request.json()
        name = str(payload.get("name", "")).strip()
        content = str(payload.get("content", "")).strip()
        if not name or not content:
            return _err("name and content required", 400)
        existing = await get_message(self.bot.db, auth[0], name)
        await upsert_message(
            self.bot.db,
            auth[0],
            name,
            content,
            str(payload.get("action", existing["action"] if existing else "none")),
            existing["action_role_id"] if existing else 0,
            existing["action_emoji"] if existing else "",
            payload.get("container") or None,
            auth[1],
        )
        return _json({"ok": True})

    async def _handle_send_message(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        guild_id, _, guild = auth
        name = request.match_info["name"]
        payload = await request.json()
        msg = await get_message(self.bot.db, guild_id, name)
        if msg is None:
            return _err("message not found", 404)
        container = None
        if msg["container_name"]:
            container = await get_container(self.bot.db, guild_id, msg["container_name"])
        layout = compose_message(guild_id, msg["content"], container)

        if payload.get("update"):
            channel = guild.get_channel(int(msg["channel_id"] or 0))
            if not isinstance(channel, discord.TextChannel) or not msg["message_id"]:
                return _err("this message hasn't been posted yet", 404)
            try:
                posted = await channel.fetch_message(int(msg["message_id"]))
                await posted.edit(view=layout)
            except discord.NotFound:
                return _err("the posted message was deleted - send it again", 404)
            except discord.HTTPException as exc:
                return _err(str(exc), 500)
            return _json({"ok": True, "message_id": posted.id})

        channel = guild.get_channel(int(payload.get("channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            return _err("channel not found or not a text channel", 404)
        try:
            posted = await channel.send(view=layout)
        except discord.HTTPException as exc:
            return _err(str(exc), 500)
        await set_posted(self.bot.db, guild_id, name, channel.id, posted.id)
        return _json({"ok": True, "message_id": posted.id})

    async def _handle_update_message(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        name = request.match_info["name"]
        msg = await get_message(self.bot.db, auth[0], name)
        if msg is None:
            return _err("message not found", 404)
        payload = await request.json()
        await upsert_message(
            self.bot.db,
            auth[0],
            name,
            payload.get("content", msg["content"]),
            msg["action"],
            msg["action_role_id"],
            msg["action_emoji"],
            payload.get("container", msg["container_name"]),
            auth[1],
        )
        return _json({"ok": True})

    async def _handle_delete_message(self, request: web.Request) -> web.Response:
        auth = await self._guild(request)
        if isinstance(auth, web.Response):
            return auth
        name = request.match_info["name"]
        msg = await get_message(self.bot.db, auth[0], name)
        await delete_message(self.bot.db, auth[0], name)
        if msg and msg["container_name"] == name:
            await delete_container(self.bot.db, auth[0], name)
        return _json({"ok": True})

    async def _serve_index(self, request: web.Request) -> web.Response:
        return await self._serve_html("index.html")

    async def _serve_dashboard(self, request: web.Request) -> web.Response:
        return await self._serve_html("dashboard.html")

    async def _serve_docs(self, request: web.Request) -> web.Response:
        return await self._serve_html("docs.html")

    async def _serve_html(self, filename: str) -> web.Response:
        path = os.path.join(os.path.dirname(__file__), "static", filename)
        with open(path, "r", encoding="utf-8") as file:
            return web.Response(text=file.read(), content_type="text/html")

    async def _serve_static(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        path = os.path.join(os.path.dirname(__file__), "static", filename)
        if ".." in filename or not os.path.exists(path):
            raise web.HTTPNotFound()
        content_type = "text/plain"
        if filename.endswith(".js"):
            content_type = "application/javascript"
        elif filename.endswith(".css"):
            content_type = "text/css"
        with open(path, "r", encoding="utf-8") as file:
            return web.Response(text=file.read(), content_type=content_type)
