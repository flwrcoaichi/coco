from __future__ import annotations

import aiosqlite

from src.utils.logger import get_logger

log = get_logger("data.db")

_SCHEMA = """
create table if not exists guild_config (
    guild_id integer primary key,
    data text not null default '{}'
);

create table if not exists twitch_chat_settings (
    guild_id integer primary key,
    twitch_channel text not null default '',
    enabled integer not null default 0,
    sub_only integer not null default 0,
    shoutout_channel_id integer not null default 0,
    shoutout_message text not null default '{user} was last live playing {game} - go give them a follow at {url}!',
    clip_channel_id integer not null default 0,
    owner_discord_id integer not null default 0
);
create table if not exists twitch_auth (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL    
);
create table if not exists twitch_chat_commands (
    guild_id integer not null,
    trigger text not null,
    kind text not null default 'random',
    template text not null default '',
    min_roll integer not null default 0,
    max_roll integer not null default 100,
    primary key (guild_id, trigger)
);

create table if not exists twitch_watchtime (
    guild_id integer not null,
    twitch_login text not null,
    seconds integer not null default 0,
    primary key (guild_id, twitch_login)
);

create table if not exists economy_balances (
    guild_id integer not null,
    user_id integer not null,
    balance integer not null default 0,
    last_work integer not null default 0,
    last_daily integer not null default 0,
    primary key (guild_id, user_id)
);

create table if not exists economy_twitch_balances (
    guild_id integer not null,
    twitch_login text not null,
    balance integer not null default 0,
    last_checkin integer not null default 0,
    primary key (guild_id, twitch_login)
);

create table if not exists twitch_join_queue (
    guild_id integer not null,
    twitch_login text not null,
    joined_at integer not null,
    primary key (guild_id, twitch_login)
);

create table if not exists color_roles (
    guild_id integer not null,
    user_id integer not null,
    role_id integer not null,
    primary key (guild_id, user_id)
);

create table if not exists raid_config (
    guild_id integer primary key,
    enabled integer not null default 1,
    join_threshold integer not null default 8,
    join_window integer not null default 10,
    account_age_min_days integer not null default 3,
    action text not null default 'kick',
    log_channel_id integer not null default 0,
    lockdown_active integer not null default 0
);

create table if not exists account_links (
    guild_id integer not null,
    discord_user_id integer not null,
    twitch_login text not null,
    linked_at integer not null,
    primary key (guild_id, discord_user_id),
    unique (guild_id, twitch_login)
);

create table if not exists infractions (
    id integer primary key autoincrement,
    guild_id integer not null,
    target_id integer not null,
    target_name text not null,
    moderator_id integer not null,
    infraction_type text not null,
    reason text not null,
    duration integer,
    created_at integer not null
);

create table if not exists permission_overrides (
    guild_id integer not null,
    role_id integer not null,
    node text not null,
    primary key (guild_id, role_id, node)
);

create table if not exists twitch_streamers (
    id integer primary key autoincrement,
    twitch_user_id text not null,
    twitch_username text not null,
    live_message_channel_id integer not null default 0,
    live_message_id integer not null default 0,
    guild_id integer not null default 0,
    discord_channel_id integer not null default 0,
    ping_role_id integer not null default 0,
    custom_message text not null default '{user} is live!',
    footer_message text not null default '',
    accent_color integer not null default 9520895,
    subscription_id text not null default '',
    is_live integer not null default 0
);

create table if not exists ticket_panels (
    id integer primary key autoincrement,
    guild_id integer not null,
    channel_id integer not null,
    message_id integer,
    category_id integer,
    staff_role_id integer,
    title text not null default 'support',
    description text not null default ''
);

create table if not exists tickets (
    id integer primary key autoincrement,
    guild_id integer not null,
    channel_id integer not null unique,
    opener_id integer not null,
    panel_id integer not null,
    reason text not null default '',
    status text not null default 'open',
    created_at integer not null,
    closed_at integer
);

create table if not exists button_containers (
    guild_id integer not null,
    name text not null,
    created_by integer not null,
    items text not null default '[]',
    accent_color integer,
    primary key (guild_id, name)
);

create table if not exists radio_playlist (
    id integer primary key autoincrement,
    guild_id integer not null,
    url text not null,
    title text not null default '',
    added_by integer not null,
    added_at integer not null
);

create table if not exists radio_state (
    guild_id integer primary key,
    enabled integer not null default 0,
    voice_channel_id integer not null default 0,
    shuffle integer not null default 1
);

create table if not exists custom_messages (
    guild_id integer not null,
    name text not null,
    channel_id integer not null default 0,
    message_id integer not null default 0,
    content text not null default '',
    action text not null default 'none',
    action_role_id integer not null default 0,
    action_emoji text not null default '',
    container_name text,
    created_by integer not null,
    primary key (guild_id, name)
);

create table if not exists channel_lock_state (
    guild_id integer not null,
    channel_id integer not null,
    role_id integer not null,
    prior_send_messages integer,
    locked_at integer not null,
    primary key (guild_id, channel_id, role_id)
);
"""


class Database:
    """single aiosqlite connection + schema, shared by every cog via bot.db.

    all schema creation and migration lives here, in one place - cogs never
    run `create table` themselves. if you add a new table for a cog, add it
    to `_SCHEMA` (or a migration below) instead of creating it ad-hoc.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute("pragma journal_mode=WAL")
        await self._conn.execute("pragma foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._migrate_twitch_streamers()
        await self._migrate_custom_messages_container()
        await self._migrate_live_message_columns()
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _migrate_twitch_streamers(self) -> None:
        """older deployments of this bot predate multi-guild support and may have
        a `twitch_streamers` table without a `guild_id` column. add it in place
        rather than dropping data."""
        assert self._conn is not None
        cursor = await self._conn.execute("pragma table_info(twitch_streamers)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "guild_id" not in columns:
            log.info("migrating twitch_streamers: adding guild_id column")
            await self._conn.execute(
                "alter table twitch_streamers add column guild_id integer not null default 0"
            )
        try:
            await self._conn.execute(
                "create unique index if not exists idx_twitch_streamer_guild"
                " on twitch_streamers (twitch_user_id, guild_id)"
            )
        except aiosqlite.OperationalError:
            log.warning(
                "could not create unique index on twitch_streamers"
                " (duplicate twitch_user_id/guild_id rows exist) - leaving as-is"
            )
    async def _migrate_live_message_columns(self) -> None:
        cols = {row[1] for row in await (await self._conn.execute(
            "pragma table_info(twitch_streamers)"
        )).fetchall()}
        if "live_message_channel_id" not in cols:
            await self._conn.execute(
                "alter table twitch_streamers add column live_message_channel_id"
                " integer not null default 0"
            )
        if "live_message_id" not in cols:
            await self._conn.execute(
                "alter table twitch_streamers add column live_message_id"
                " integer not null default 0"
            )
    async def _migrate_custom_messages_container(self) -> None:
        """older deployments predate the button_containers-backed button system
        and may lack the container_name column. add it in place."""
        assert self._conn is not None
        cursor = await self._conn.execute("pragma table_info(custom_messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "container_name" not in columns:
            log.info("migrating custom_messages: adding container_name column")
            await self._conn.execute(
                "alter table custom_messages add column container_name text"
            )

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        assert self._conn is not None
        await self._conn.execute(query, params)
        await self._conn.commit()

    async def fetchone(self, query: str, params: tuple[object, ...] = ()) -> tuple[object, ...] | None:
        assert self._conn is not None
        cursor = await self._conn.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    async def fetchall(self, query: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        assert self._conn is not None
        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return list(rows)
