from __future__ import annotations

import time

from src.data.db import Database

_SETTINGS_COLUMNS = (
    "guild_id, twitch_channel, enabled, sub_only, shoutout_channel_id,"
    " shoutout_message, clip_channel_id, owner_discord_id"
)
_SETTINGS_KEYS = (
    "guild_id",
    "twitch_channel",
    "enabled",
    "sub_only",
    "shoutout_channel_id",
    "shoutout_message",
    "clip_channel_id",
    "owner_discord_id",
)

_DEFAULT_SHOUTOUT = "{user} was last live playing {game} - go give them a follow at {url}!"


def _row_to_settings(row: tuple[object, ...]) -> dict[str, object]:
    return dict(zip(_SETTINGS_KEYS, row))


async def get_settings(db: Database, guild_id: int) -> dict[str, object] | None:
    row = await db.fetchone(
        f"select {_SETTINGS_COLUMNS} from twitch_chat_settings where guild_id = ?",
        (guild_id,),
    )
    return _row_to_settings(row) if row else None


async def get_all_enabled_settings(db: Database) -> list[dict[str, object]]:
    rows = await db.fetchall(
        f"select {_SETTINGS_COLUMNS} from twitch_chat_settings where enabled = 1"
    )
    return [_row_to_settings(r) for r in rows]


async def upsert_settings(db: Database, guild_id: int, **fields: object) -> None:
    existing = await get_settings(db, guild_id)
    if existing is None:
        await db.execute(
            "insert into twitch_chat_settings (guild_id, shoutout_message) values (?, ?)",
            (guild_id, _DEFAULT_SHOUTOUT),
        )
    if not fields:
        return
    query = f"update twitch_chat_settings set {', '.join(f'{k} = ?' for k in fields)} where guild_id = ?"
    await db.execute(query, (*fields.values(), guild_id))


async def set_channel(db: Database, guild_id: int, twitch_channel: str) -> None:
    await upsert_settings(db, guild_id, twitch_channel=twitch_channel.lower(), enabled=1)


async def set_enabled(db: Database, guild_id: int, enabled: bool) -> None:
    await upsert_settings(db, guild_id, enabled=1 if enabled else 0)




_CMD_COLUMNS = "guild_id, trigger, kind, template, min_roll, max_roll"
_CMD_KEYS = ("guild_id", "trigger", "kind", "template", "min_roll", "max_roll")


def _row_to_cmd(row: tuple[object, ...]) -> dict[str, object]:
    return dict(zip(_CMD_KEYS, row))


async def add_command(
    db: Database,
    guild_id: int,
    trigger: str,
    template: str,
    kind: str = "random",
    min_roll: int = 0,
    max_roll: int = 100,
) -> None:
    trigger = trigger.lower()
    if not trigger.startswith("!"):
        trigger = f"!{trigger}"
    await db.execute(
        "insert into twitch_chat_commands (guild_id, trigger, kind, template, min_roll, max_roll)"
        " values (?, ?, ?, ?, ?, ?)"
        " on conflict(guild_id, trigger) do update set"
        " kind = excluded.kind, template = excluded.template,"
        " min_roll = excluded.min_roll, max_roll = excluded.max_roll",
        (guild_id, trigger, kind, template, min_roll, max_roll),
    )


async def remove_command(db: Database, guild_id: int, trigger: str) -> None:
    trigger = trigger.lower()
    if not trigger.startswith("!"):
        trigger = f"!{trigger}"
    await db.execute(
        "delete from twitch_chat_commands where guild_id = ? and trigger = ?",
        (guild_id, trigger),
    )


async def get_command(db: Database, guild_id: int, trigger: str) -> dict[str, object] | None:
    row = await db.fetchone(
        f"select {_CMD_COLUMNS} from twitch_chat_commands where guild_id = ? and trigger = ?",
        (guild_id, trigger.lower()),
    )
    return _row_to_cmd(row) if row else None


async def list_commands(db: Database, guild_id: int) -> list[dict[str, object]]:
    rows = await db.fetchall(
        f"select {_CMD_COLUMNS} from twitch_chat_commands where guild_id = ?", (guild_id,)
    )
    return [_row_to_cmd(r) for r in rows]




async def add_watchtime(db: Database, guild_id: int, twitch_login: str, seconds: int) -> None:
    if seconds <= 0:
        return
    await db.execute(
        "insert into twitch_watchtime (guild_id, twitch_login, seconds) values (?, ?, ?)"
        " on conflict(guild_id, twitch_login) do update set seconds = seconds + excluded.seconds",
        (guild_id, twitch_login.lower(), seconds),
    )


async def get_watchtime(db: Database, guild_id: int, twitch_login: str) -> int:
    row = await db.fetchone(
        "select seconds from twitch_watchtime where guild_id = ? and twitch_login = ?",
        (guild_id, twitch_login.lower()),
    )
    return int(row[0]) if row else 0




async def queue_join(db: Database, guild_id: int, twitch_login: str) -> bool:
    """returns False if the user was already queued."""
    existing = await db.fetchone(
        "select 1 from twitch_join_queue where guild_id = ? and twitch_login = ?",
        (guild_id, twitch_login.lower()),
    )
    if existing:
        return False
    await db.execute(
        "insert into twitch_join_queue (guild_id, twitch_login, joined_at) values (?, ?, ?)",
        (guild_id, twitch_login.lower(), int(time.time())),
    )
    return True


async def list_queue(db: Database, guild_id: int) -> list[str]:
    rows = await db.fetchall(
        "select twitch_login from twitch_join_queue where guild_id = ? order by joined_at asc",
        (guild_id,),
    )
    return [str(r[0]) for r in rows]


async def clear_queue(db: Database, guild_id: int) -> None:
    await db.execute("delete from twitch_join_queue where guild_id = ?", (guild_id,))
