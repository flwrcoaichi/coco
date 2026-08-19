from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from src.data.db import Database


@dataclass
class ModerationConfig:
    require_confirm: bool = True

    mute_channel: int | None = None

    lockdown_include_member_role: bool = True

    warn_default_reason: list[str] = field(default_factory=lambda: ["being disruptive"])
    warn_dm: list[str] = field(
        default_factory=lambda: ["you were warned in a server you're in: {reason}"]
    )
    warn_channel: list[str] = field(default_factory=lambda: ["{user} has been warned: {reason}"])

    kick_default_reason: list[str] = field(default_factory=lambda: ["breaking server rules"])
    kick_dm: list[str] = field(
        default_factory=lambda: ["you were kicked from a server you're in: {reason}"]
    )
    kick_channel: list[str] = field(default_factory=lambda: ["{user} has been kicked: {reason}"])

    ban_default_reason: list[str] = field(default_factory=lambda: ["breaking server rules"])
    ban_default_duration: str = "forever"
    ban_dm: list[str] = field(
        default_factory=lambda: ["you were banned from a server you're in: {reason}"]
    )
    ban_channel: list[str] = field(default_factory=lambda: ["{user} has been banned: {reason}"])

    mute_default_reason: list[str] = field(default_factory=lambda: ["being disruptive"])
    mute_default_duration: str = "1h"
    mute_dm: list[str] = field(
        default_factory=lambda: ["you were muted in a server you're in: {reason}"]
    )
    mute_channel_msg: list[str] = field(default_factory=lambda: ["{user} has been muted: {reason}"])

    slowmode_default_reason: list[str] = field(default_factory=lambda: ["chat moving too fast"])
    shutdown_default_reason: list[str] = field(default_factory=lambda: ["raid response"])


@dataclass
class DashboardConfig:
    """settings surfaced in the web dashboard's config panel."""

    moderator_role: int | None = None
    admin_role: int | None = None
    member_role: int | None = None
    image_role: int | None = None
    music_role: int | None = None
    ticket_channel: int | None = None
    ticket_message: str = "create a ticket for help"

    announcement_channel: int | None = None
    announcement_role: int | None = None

    join_channel: int | None = None
    join_messages: list[str] = field(
        default_factory=lambda: ["welcome to the server, {user}!"]
    )
    leave_channel: int | None = None
    leave_messages: list[str] = field(
        default_factory=lambda: ["{user} left the server."]
    )

    widget_enabled: bool = False


@dataclass
class GuildConfig:
    guild_id: int
    moderation: ModerationConfig = field(default_factory=ModerationConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    @classmethod
    async def load(cls, db: Database, guild_id: int) -> "GuildConfig":
        row = await db.fetchone(
            "select data from guild_config where guild_id = ?", (guild_id,)
        )
        if row is None:
            return cls(guild_id=guild_id)
        try:
            payload = json.loads(str(row[0]))
        except json.JSONDecodeError:
            return cls(guild_id=guild_id)
        return cls(
            guild_id=guild_id,
            moderation=ModerationConfig(**payload.get("moderation", {})),
            dashboard=DashboardConfig(**payload.get("dashboard", {})),
        )

    async def save(self, db: Database) -> None:
        payload = json.dumps({"moderation": asdict(self.moderation), "dashboard": asdict(self.dashboard)})
        await db.execute(
            "insert into guild_config (guild_id, data) values (?, ?)"
            " on conflict (guild_id) do update set data = excluded.data",
            (self.guild_id, payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self.dashboard), **{"moderation": asdict(self.moderation)}}



_DASHBOARD_KEYS = {
    "moderator_role",
    "admin_role",
    "member_role",
    "image_role",
    "music_role",
    "ticket_channel",
    "ticket_message",
    "announcement_channel",
    "announcement_role",
    "join_channel",
    "join_messages",
    "leave_channel",
    "leave_messages",
    "widget_enabled",
}

_DASHBOARD_INT_KEYS = {
    "moderator_role",
    "admin_role",
    "member_role",
    "image_role",
    "music_role",
    "ticket_channel",
    "announcement_channel",
    "announcement_role",
    "join_channel",
    "leave_channel",
}
_DASHBOARD_STR_KEYS = {"ticket_message"}
_DASHBOARD_LIST_KEYS = {"join_messages", "leave_messages"}
_DASHBOARD_BOOL_KEYS = {"widget_enabled"}


async def get_all_config(db: Database, guild_id: int) -> dict[str, Any]:
    cfg = await GuildConfig.load(db, guild_id)
    return asdict(cfg.dashboard)


async def set_config(db: Database, guild_id: int, key: str, value: Any) -> None:
    if key not in _DASHBOARD_KEYS:
        return
    cfg = await GuildConfig.load(db, guild_id)
    if key in _DASHBOARD_STR_KEYS:
        setattr(cfg.dashboard, key, str(value))
    elif key in _DASHBOARD_BOOL_KEYS:
        setattr(cfg.dashboard, key, str(value).strip().lower() in ("1", "true", "yes", "on"))
    elif key in _DASHBOARD_LIST_KEYS:
        if isinstance(value, list):
            setattr(cfg.dashboard, key, [str(item) for item in value])
        else:
            return
    else:
        try:
            setattr(cfg.dashboard, key, int(value))
        except (TypeError, ValueError):
            return
    await cfg.save(db)


_MODERATION_INT_KEYS = {"mute_channel"}
_MODERATION_BOOL_KEYS = {"require_confirm", "lockdown_include_member_role"}
_MODERATION_LIST_KEYS = {
    "warn_default_reason",
    "warn_dm",
    "warn_channel",
    "kick_default_reason",
    "kick_dm",
    "kick_channel",
    "ban_default_reason",
    "ban_dm",
    "ban_channel",
    "mute_default_reason",
    "mute_dm",
    "mute_channel_msg",
}


async def get_moderation_config(db: Database, guild_id: int) -> dict[str, Any]:
    cfg = await GuildConfig.load(db, guild_id)
    return asdict(cfg.moderation)


async def set_moderation_config(db: Database, guild_id: int, payload: dict[str, Any]) -> None:
    cfg = await GuildConfig.load(db, guild_id)
    for key, value in payload.items():
        if key in _MODERATION_INT_KEYS:
            try:
                setattr(cfg.moderation, key, int(value) if value not in (None, "") else None)
            except (TypeError, ValueError):
                continue
        elif key in _MODERATION_BOOL_KEYS:
            setattr(cfg.moderation, key, bool(value))
        elif key in _MODERATION_LIST_KEYS and isinstance(value, list):
            setattr(cfg.moderation, key, [str(item) for item in value])
    await cfg.save(db)


async def delete_config(db: Database, guild_id: int, key: str) -> None:
    if key not in _DASHBOARD_KEYS:
        return
    cfg = await GuildConfig.load(db, guild_id)
    default = DashboardConfig()
    setattr(cfg.dashboard, key, getattr(default, key))
    await cfg.save(db)
