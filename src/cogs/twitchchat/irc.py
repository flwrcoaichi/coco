from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.utils.logger import get_logger

log = get_logger("twitchchat.irc")

TWITCH_IRC_HOST = "irc.chat.twitch.tv"
TWITCH_IRC_PORT = 6667

TWITCH_BOT_USERNAME = os.getenv("TWITCH_BOT_USERNAME", "")

TokenProvider = Callable[[], Awaitable[str | None]]


@dataclass
class ChatMessage:
    channel: str  
    user_login: str
    display_name: str
    text: str
    badges: set[str]
    is_mod: bool
    is_sub: bool
    is_broadcaster: bool
    room_id: str
    source_room_id: str

    @property
    def is_foreign(self) -> bool:
        """True if this message came from a different channel's chat via
        twitch's shared-chat feature, not the room we actually joined."""
        return bool(self.source_room_id) and self.source_room_id != self.room_id


MessageCallback = Callable[[ChatMessage], Awaitable[None]]


def _parse_tags(raw: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for pair in raw.split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            tags[k] = v
    return tags


class TwitchIRCClient:
    """single IRC connection for one bot account that can join/part several
    channels at once - one instance is shared across every configured guild.
    """

    def __init__(self, on_message: MessageCallback, get_token: TokenProvider) -> None:
        self._on_message = on_message
        self._get_token = get_token
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._channels: set[str] = set()
        self._closing = False
        self._connected = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
        if self._writer is not None:
            self._writer.close()

    async def join(self, channel: str) -> None:
        channel = channel.lower().lstrip("#")
        self._channels.add(channel)
        if self._writer is not None:
            await self._connected.wait()
            self._writer.write(f"JOIN #{channel}\r\n".encode())
            await self._writer.drain()

    async def part(self, channel: str) -> None:
        channel = channel.lower().lstrip("#")
        self._channels.discard(channel)
        if self._writer is not None:
            self._writer.write(f"PART #{channel}\r\n".encode())
            await self._writer.drain()

    async def send(self, channel: str, message: str) -> None:
        channel = channel.lower().lstrip("#")
        if self._writer is None:
            return
        await self._connected.wait()
        self._writer.write(f"PRIVMSG #{channel} :{message}\r\n".encode())
        await self._writer.drain()

    async def _run(self) -> None:
        while not self._closing:
            token = await self._get_token()
            if token is None:
                log.info("no twitch bot token yet - waiting for /auth/twitch to be completed")
                await asyncio.sleep(30)
                continue
            try:
                await self._connect_and_listen(token)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("twitch irc connection dropped, reconnecting in 5s")
                self._connected.clear()
                await asyncio.sleep(5)

    async def _connect_and_listen(self, token: str) -> None:
        reader, writer = await asyncio.open_connection(TWITCH_IRC_HOST, TWITCH_IRC_PORT)
        self._reader, self._writer = reader, writer

        writer.write(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
        writer.write(f"PASS oauth:{token}\r\n".encode())
        writer.write(f"NICK {TWITCH_BOT_USERNAME.lower()}\r\n".encode())
        await writer.drain()

        for channel in list(self._channels):
            writer.write(f"JOIN #{channel}\r\n".encode())
        await writer.drain()

        self._connected.set()
        log.info("twitch irc connected as %s, joined %d channel(s)", TWITCH_BOT_USERNAME, len(self._channels))

        buf = ""
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                await self._handle_line(line)

    async def _handle_line(self, line: str) -> None:
        if line.startswith("PING"):
            assert self._writer is not None
            self._writer.write(b"PONG :tmi.twitch.tv\r\n")
            await self._writer.drain()
            return

        if "PRIVMSG" not in line:
            return

        tags: dict[str, str] = {}
        rest = line
        if line.startswith("@"):
            tag_part, rest = line[1:].split(" ", 1)
            tags = _parse_tags(tag_part)

        try:
            prefix, remainder = rest.split(" PRIVMSG ", 1)
            login = prefix.split("!", 1)[0].lstrip(":")
            channel_part, _, msg_part = remainder.partition(" :")
            channel = channel_part.strip().lstrip("#")
            text = msg_part.strip()
        except ValueError:
            return

        badges_raw = tags.get("badges", "")
        badges = {b.split("/")[0] for b in badges_raw.split(",") if b}
        display_name = tags.get("display-name") or login
        is_broadcaster = "broadcaster" in badges

        msg = ChatMessage(
            channel=channel,
            user_login=login,
            display_name=display_name,
            text=text,
            badges=badges,
            is_mod=("moderator" in badges or is_broadcaster),
            is_sub=("subscriber" in badges or "founder" in badges or "vip" in badges),
            is_broadcaster=is_broadcaster,
            room_id=tags.get("room-id", ""),
            source_room_id=tags.get("source-room-id", ""),
        )
        try:
            await self._on_message(msg)
        except Exception:
            log.exception("chat message handler failed")