from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from src.cogs.twitch.db import save_redeem_auth
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitch.redeem_auth")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
REDEEM_REDIRECT_URI = os.getenv("TWITCH_REDEEM_REDIRECT_URI", "http://localhost:8084/auth/twitch/redeems/callback")
REDEEM_SCOPES = "channel:read:redemptions"

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
USERS_URL = "https://api.twitch.tv/helix/users"

_REFRESH_BUFFER_SECONDS = 60


async def get_valid_broadcaster_token(bot: "Bot", guild_id: int) -> str | None:
    """returns a usable bearer token for whoever authorized redeems for this
    guild, refreshing first if needed. None if nobody's done that yet."""
    from src.cogs.twitch.db import get_redeem_auth  # local import, avoids a cycle at module load

    auth = await get_redeem_auth(bot.db, guild_id)
    if auth is None or not auth["access_token"]:
        return None
    if int(auth["expires_at"]) - _REFRESH_BUFFER_SECONDS <= int(time.time()):
        return await _refresh(bot, guild_id, str(auth["refresh_token"]), str(auth["broadcaster_id"]), str(auth["broadcaster_login"]))
    return str(auth["access_token"])


async def _refresh(bot: "Bot", guild_id: int, refresh_token: str, broadcaster_id: str, broadcaster_login: str) -> str | None:
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            TOKEN_URL,
            params={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if resp.status != 200:
            log.error("redeem token refresh failed for guild %s: %s %s", guild_id, resp.status, await resp.text())
            return None
        data = await resp.json()

    expires_at = int(time.time()) + int(data["expires_in"])
    await save_redeem_auth(
        bot.db, guild_id, broadcaster_id, broadcaster_login, data["access_token"], data["refresh_token"], expires_at
    )
    return str(data["access_token"])


def build_app(bot: "Bot") -> web.Application:
    app = web.Application()

    async def start(request: web.Request) -> web.Response:
        guild_id = request.query.get("guild_id", "")
        if not guild_id.isdigit():
            return web.Response(status=400, text="missing or invalid guild_id")
        query = urlencode(
            {
                "client_id": TWITCH_CLIENT_ID,
                "redirect_uri": REDEEM_REDIRECT_URI,
                "response_type": "code",
                "scope": REDEEM_SCOPES,
                "state": guild_id,
            }
        )
        raise web.HTTPFound(f"{AUTHORIZE_URL}?{query}")

    async def callback(request: web.Request) -> web.Response:
        error = request.query.get("error")
        if error:
            return web.Response(status=400, text=f"authentication failed: {error}")

        code = request.query.get("code")
        guild_id_str = request.query.get("state", "")
        if not code or not guild_id_str.isdigit():
            return web.Response(status=400, text="missing code or state")
        guild_id = int(guild_id_str)

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                TOKEN_URL,
                params={
                    "client_id": TWITCH_CLIENT_ID,
                    "client_secret": TWITCH_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": REDEEM_REDIRECT_URI,
                },
            )
            if resp.status != 200:
                log.error("redeem token exchange failed: %s %s", resp.status, await resp.text())
                return web.Response(status=500, text="failed to exchange authorization code")
            data = await resp.json()

            user_resp = await session.get(
                USERS_URL,
                headers={"Client-Id": TWITCH_CLIENT_ID, "Authorization": f"Bearer {data['access_token']}"},
            )
            user_data = await user_resp.json()
            if not user_data.get("data"):
                return web.Response(status=500, text="couldn't look up your twitch account")
            broadcaster_id = user_data["data"][0]["id"]
            broadcaster_login = user_data["data"][0]["login"]

        expires_at = int(time.time()) + int(data["expires_in"])
        await save_redeem_auth(
            bot.db, guild_id, broadcaster_id, broadcaster_login, data["access_token"], data["refresh_token"], expires_at
        )
        log.info("redeem auth completed for guild %s (%s)", guild_id, broadcaster_login)
        return web.Response(
            text=f"connected as {broadcaster_login}! you can close this window and run /twitchredeem list in discord."
        )

    app.router.add_get("/auth/twitch/redeems", start)
    app.router.add_get("/auth/twitch/redeems/callback", callback)
    return app


class RedeemAuthServer:
    """one small server per bot instance for the 'let coco read my channel
    point rewards' flow. each server owner visits /auth/twitch/redeems?guild_id=...
    (linked from /twitchredeem authorize), logs in as themselves - not the bot
    account - and approves. runs on its own port since it needs its own
    redirect URI registered on the twitch app."""

    def __init__(self, bot: "Bot", host: str = "0.0.0.0", port: int = 8084) -> None:
        self._app = build_app(bot)
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        log.info("twitch redeem-auth listener started on %s:%s/auth/twitch/redeems", self._host, self._port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
