from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class BotConfig:
    token: str = os.getenv("DISCORD_TOKEN", "")
    command_prefix: str = os.getenv("COMMAND_PREFIX", ">>")
    db_path: str = os.getenv("DB_PATH", "data/bot.db")

    dashboard_enabled: bool = _bool("DASHBOARD_ENABLED", True)
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    dashboard_port: int = int(os.getenv("DASHBOARD_PORT", "8081"))
    dashboard_origin: str = os.getenv("DASHBOARD_ORIGIN", "*")

    twitch_webhook_enabled: bool = _bool("TWITCH_WEBHOOK_ENABLED", True)
    twitch_webhook_host: str = os.getenv("TWITCH_WEBHOOK_HOST", "0.0.0.0")
    twitch_webhook_port: int = int(os.getenv("TWITCH_WEBHOOK_PORT", "8082"))

    twitch_webhook_callback_url: str = os.getenv("TWITCH_WEBHOOK_CALLBACK_URL", "")

    discord_client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
