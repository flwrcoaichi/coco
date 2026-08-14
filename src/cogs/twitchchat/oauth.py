from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitchchat.oauth")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
TWITCH_REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI", "http://localhost:8083/auth/twitch/callback")
TWITCH_SCOPES = os.getenv(
    "TWITCH_SCOPES", "chat:read chat:edit moderator:read:followers clips:edit"
)

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"


_REFRESH_BUFFER_SECONDS = 60


async def get_tokens(bot: "Bot") -> dict[str, object] | None:
    row = await bot.db.fetchone(
        "select access_token, refresh_token, expires_at from twitch_auth where id = 1"
    )
    if row is None:
        return None
    return {"access_token": row[0], "refresh_token": row[1], "expires_at": int(row[2])}


async def save_tokens(bot: "Bot", access_token: str, refresh_token: str, expires_in: int) -> None:
    expires_at = int(time.time()) + int(expires_in)
    await bot.db.execute(
        "insert into twitch_auth (id, access_token, refresh_token, expires_at)"
        " values (1, ?, ?, ?)"
        " on conflict(id) do update set access_token = excluded.access_token,"
        " refresh_token = excluded.refresh_token, expires_at = excluded.expires_at",
        (access_token, refresh_token, expires_at),
    )


async def _refresh(bot: "Bot", refresh_token: str) -> str | None:
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
            log.error("token refresh failed: %s %s", resp.status, await resp.text())
            return None
        data = await resp.json()

    await save_tokens(bot, data["access_token"], data["refresh_token"], data["expires_in"])
    return str(data["access_token"])


async def get_valid_access_token(bot: "Bot") -> str | None:
    """returns a usable (unprefixed) bearer token for the bot account,
    refreshing it first if it's expired or about to be. returns None if
    nobody has completed the /auth/twitch flow yet."""
    tokens = await get_tokens(bot)
    if tokens is None:
        return None
    if int(tokens["expires_at"]) - _REFRESH_BUFFER_SECONDS <= int(time.time()):
        return await _refresh(bot, str(tokens["refresh_token"]))
    return str(tokens["access_token"])


def build_app(bot: "Bot") -> web.Application:
    app = web.Application()

    async def start(request: web.Request) -> web.Response:
        query = urlencode(
            {
                "client_id": TWITCH_CLIENT_ID,
                "redirect_uri": TWITCH_REDIRECT_URI,
                "response_type": "code",
                "scope": TWITCH_SCOPES,
            }
        )
        raise web.HTTPFound(f"{AUTHORIZE_URL}?{query}")

    async def callback(request: web.Request) -> web.Response:
        error = request.query.get("error")
        if error:
            return web.Response(status=400, text=f"authentication failed: {error}")

        code = request.query.get("code")
        if not code:
            return web.Response(status=400, text="missing code")

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                TOKEN_URL,
                params={
                    "client_id": TWITCH_CLIENT_ID,
                    "client_secret": TWITCH_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": TWITCH_REDIRECT_URI,
                },
            )
            if resp.status != 200:
                log.error("token exchange failed: %s %s", resp.status, await resp.text())
                return web.Response(status=500, text="failed to exchange authorization code")
            data = await resp.json()

        await save_tokens(bot, data["access_token"], data["refresh_token"], data["expires_in"])
        log.info("twitch bot account authenticated, tokens saved")
        return web.Response(text="authenticated successfully! you can close this window.")

    app.router.add_get("/auth/twitch", start)
    app.router.add_get("/auth/twitch/callback", callback)
    return app


class TwitchAuthServer:
    """tiny standalone server for the one-time bot-account auth flow.
    visit http://<host>:<port>/auth/twitch, log in as the bot account
    (e.g. cocoFLWR), approve, done - tokens are stored and refreshed
    automatically after that."""

    def __init__(self, bot: "Bot", host: str = "0.0.0.0", port: int = 8083) -> None:
        self._app = build_app(bot)
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        log.info("twitch bot-auth listener started on %s:%s/auth/twitch", self._host, self._port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
