from __future__ import annotations

from src.data.db import Database

_COLUMNS = (
    "twitch_user_id, twitch_username, guild_id, discord_channel_id, ping_role_id,"
    " custom_message, footer_message, accent_color, subscription_id, is_live,"
    " live_message_channel_id, live_message_id"
)
_KEYS = (
    "twitch_user_id",
    "twitch_username",
    "guild_id",
    "discord_channel_id",
    "ping_role_id",
    "custom_message",
    "footer_message",
    "accent_color",
    "subscription_id",
    "is_live",
    "live_message_channel_id",
    "live_message_id",
)


def _row_to_dict(row: tuple[object, ...]) -> dict[str, object]:
    return dict(zip(_KEYS, row))


async def add_streamer(
    db: Database,
    twitch_user_id: str,
    twitch_username: str,
    discord_channel_id: int,
    guild_id: int = 0,
) -> None:
    await db.execute(
        "insert into twitch_streamers (twitch_user_id, twitch_username, guild_id, discord_channel_id)"
        " values (?, ?, ?, ?)",
        (twitch_user_id, twitch_username, guild_id, discord_channel_id),
    )


async def get_streamer(db: Database, twitch_user_id: str, guild_id: int | None = None) -> dict[str, object] | None:
    query = f"select {_COLUMNS} from twitch_streamers where twitch_user_id = ?"
    params: tuple[object, ...] = (twitch_user_id,)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (twitch_user_id, guild_id)
    row = await db.fetchone(query, params)
    return _row_to_dict(row) if row else None


async def get_streamer_by_username(
    db: Database, username: str, guild_id: int | None = None
) -> dict[str, object] | None:
    query = (
        f"select {_COLUMNS} from twitch_streamers where twitch_username = ? collate nocase"
    )
    params: tuple[object, ...] = (username,)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (username, guild_id)
    row = await db.fetchone(query, params)
    return _row_to_dict(row) if row else None


async def get_all_streamers(db: Database) -> list[dict[str, object]]:
    rows = await db.fetchall(f"select {_COLUMNS} from twitch_streamers")
    return [_row_to_dict(r) for r in rows]


async def get_live_streamers(db: Database) -> list[dict[str, object]]:
    """streamers currently tracked as live with a message to keep fresh."""
    rows = await db.fetchall(
        f"select {_COLUMNS} from twitch_streamers where live_message_id != 0"
    )
    return [_row_to_dict(r) for r in rows]


async def remove_streamer(db: Database, twitch_user_id: str, guild_id: int | None = None) -> None:
    query = "delete from twitch_streamers where twitch_user_id = ?"
    params: tuple[object, ...] = (twitch_user_id,)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (twitch_user_id, guild_id)
    await db.execute(query, params)


async def update_streamer(
    db: Database, twitch_user_id: str, guild_id: int | None = None, **fields: object
) -> None:
    if not fields:
        return
    query = f"update twitch_streamers set {', '.join(f'{k} = ?' for k in fields)} where twitch_user_id = ?"
    params: tuple[object, ...] = (*fields.values(), twitch_user_id)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (*fields.values(), twitch_user_id, guild_id)
    await db.execute(query, params)


# ---- per-guild broadcaster auth for reading/subscribing to channel points ----
# separate from twitch_auth (the single shared bot-account token used for chat
# login) - this is the *streamer's own* token, one per guild, since reading
# their channel point rewards requires their consent, not the bot's.


async def get_redeem_auth(db: Database, guild_id: int) -> dict[str, object] | None:
    row = await db.fetchone(
        "select guild_id, broadcaster_id, broadcaster_login, access_token, refresh_token,"
        " expires_at, subscription_id from twitch_redeem_auth where guild_id = ?",
        (guild_id,),
    )
    if row is None:
        return None
    keys = (
        "guild_id", "broadcaster_id", "broadcaster_login", "access_token",
        "refresh_token", "expires_at", "subscription_id",
    )
    return dict(zip(keys, row))


async def get_redeem_auth_by_broadcaster(db: Database, broadcaster_id: str) -> dict[str, object] | None:
    row = await db.fetchone(
        "select guild_id, broadcaster_id, broadcaster_login, access_token, refresh_token,"
        " expires_at, subscription_id from twitch_redeem_auth where broadcaster_id = ?",
        (broadcaster_id,),
    )
    if row is None:
        return None
    keys = (
        "guild_id", "broadcaster_id", "broadcaster_login", "access_token",
        "refresh_token", "expires_at", "subscription_id",
    )
    return dict(zip(keys, row))


async def get_all_redeem_auths(db: Database) -> list[dict[str, object]]:
    rows = await db.fetchall(
        "select guild_id, broadcaster_id, broadcaster_login, access_token, refresh_token,"
        " expires_at, subscription_id from twitch_redeem_auth"
    )
    keys = (
        "guild_id", "broadcaster_id", "broadcaster_login", "access_token",
        "refresh_token", "expires_at", "subscription_id",
    )
    return [dict(zip(keys, r)) for r in rows]


async def save_redeem_auth(
    db: Database,
    guild_id: int,
    broadcaster_id: str,
    broadcaster_login: str,
    access_token: str,
    refresh_token: str,
    expires_at: int,
) -> None:
    await db.execute(
        "insert into twitch_redeem_auth"
        " (guild_id, broadcaster_id, broadcaster_login, access_token, refresh_token, expires_at)"
        " values (?, ?, ?, ?, ?, ?)"
        " on conflict(guild_id) do update set broadcaster_id = excluded.broadcaster_id,"
        " broadcaster_login = excluded.broadcaster_login, access_token = excluded.access_token,"
        " refresh_token = excluded.refresh_token, expires_at = excluded.expires_at",
        (guild_id, broadcaster_id, broadcaster_login, access_token, refresh_token, expires_at),
    )


async def set_redeem_subscription_id(db: Database, guild_id: int, subscription_id: str) -> None:
    await db.execute(
        "update twitch_redeem_auth set subscription_id = ? where guild_id = ?",
        (subscription_id, guild_id),
    )


async def delete_redeem_auth(db: Database, guild_id: int) -> None:
    await db.execute("delete from twitch_redeem_auth where guild_id = ?", (guild_id,))


# ---- per-guild reward -> action config ----

_ACTION_KEYS = ("guild_id", "reward_title", "action_type", "action_value")


async def set_redeem_action(
    db: Database, guild_id: int, reward_title: str, action_type: str, action_value: str
) -> None:
    await db.execute(
        "insert into twitch_redeem_actions (guild_id, reward_title, action_type, action_value)"
        " values (?, ?, ?, ?)"
        " on conflict(guild_id, reward_title) do update set"
        " action_type = excluded.action_type, action_value = excluded.action_value",
        (guild_id, reward_title.lower(), action_type, action_value),
    )


async def remove_redeem_action(db: Database, guild_id: int, reward_title: str) -> None:
    await db.execute(
        "delete from twitch_redeem_actions where guild_id = ? and reward_title = ?",
        (guild_id, reward_title.lower()),
    )


async def get_redeem_action(db: Database, guild_id: int, reward_title: str) -> dict[str, object] | None:
    row = await db.fetchone(
        "select guild_id, reward_title, action_type, action_value from twitch_redeem_actions"
        " where guild_id = ? and reward_title = ?",
        (guild_id, reward_title.lower()),
    )
    return dict(zip(_ACTION_KEYS, row)) if row else None


async def list_redeem_actions(db: Database, guild_id: int) -> list[dict[str, object]]:
    rows = await db.fetchall(
        "select guild_id, reward_title, action_type, action_value from twitch_redeem_actions"
        " where guild_id = ? order by reward_title",
        (guild_id,),
    )
    return [dict(zip(_ACTION_KEYS, r)) for r in rows]
