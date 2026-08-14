from __future__ import annotations

from src.data.db import Database


async def link_account(db: Database, guild_id: int, discord_user_id: int, twitch_login: str, ts: int) -> None:
    await db.execute(
        "insert into account_links (guild_id, discord_user_id, twitch_login, linked_at)"
        " values (?, ?, ?, ?)"
        " on conflict(guild_id, discord_user_id) do update set"
        " twitch_login = excluded.twitch_login, linked_at = excluded.linked_at",
        (guild_id, discord_user_id, twitch_login, ts),
    )


async def unlink_account(db: Database, guild_id: int, discord_user_id: int) -> None:
    await db.execute(
        "delete from account_links where guild_id = ? and discord_user_id = ?",
        (guild_id, discord_user_id),
    )


async def get_twitch_login(db: Database, guild_id: int, discord_user_id: int) -> str | None:
    row = await db.fetchone(
        "select twitch_login from account_links where guild_id = ? and discord_user_id = ?",
        (guild_id, discord_user_id),
    )
    return str(row[0]) if row else None


async def get_discord_user_id(db: Database, guild_id: int, twitch_login: str) -> int | None:
    row = await db.fetchone(
        "select discord_user_id from account_links where guild_id = ? and twitch_login = ?",
        (guild_id, twitch_login),
    )
    return int(row[0]) if row else None
