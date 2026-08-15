from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from src.cogs.economy import db as economy_db
from src.cogs.economy import links as economy_links
from src.cogs.ticketing.cog import open_ticket_for
from src.cogs.twitch.db import get_redeem_action
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitch.redeem_actions")

# what a redeem can trigger, once the redeeming twitch account is linked to a
# discord account (see economy/links.py - that link is the only thing that
# lets us reasonably act on a discord user off the back of a twitch event):
#   currency -> action_value is an int, added to their coin balance
#   role     -> action_value is a discord role id, granted (not timed - see note below)
#   ticket   -> action_value is a ticket panel id, opens a private thread for them


async def handle_redemption(bot: "Bot", guild_id: int, twitch_login: str, reward_title: str) -> None:
    action = await get_redeem_action(bot.db, guild_id, reward_title)
    if action is None:
        return

    discord_user_id = await economy_links.get_discord_user_id(bot.db, guild_id, twitch_login)
    if discord_user_id is None:
        log.info(
            "redeem '%s' fired for unlinked twitch user %s in guild %s, no action taken",
            reward_title, twitch_login, guild_id,
        )
        return

    guild = bot.get_guild(guild_id)
    if guild is None:
        return
    member = guild.get_member(discord_user_id)
    if member is None:
        return

    action_type = str(action["action_type"])
    value = str(action["action_value"])

    if action_type == "currency":
        try:
            amount = int(value)
        except ValueError:
            log.error("bad currency amount %r for redeem '%s' in guild %s", value, reward_title, guild_id)
            return
        await economy_db.add_balance(bot.db, guild_id, discord_user_id, amount)
        log.info("gave %s %s coins for redeeming '%s'", discord_user_id, amount, reward_title)

    elif action_type == "role":
        try:
            role_id = int(value)
        except ValueError:
            return
        role = guild.get_role(role_id)
        if role is None:
            log.error("role %s no longer exists for redeem '%s' in guild %s", role_id, reward_title, guild_id)
            return
        try:
            await member.add_roles(role, reason=f"twitch redeem: {reward_title}")
        except discord.HTTPException:
            log.exception("failed to add role for redeem '%s' in guild %s", reward_title, guild_id)

    elif action_type == "ticket":
        try:
            panel_id = int(value)
        except ValueError:
            return
        result = await open_ticket_for(bot, guild, panel_id, member, reason=f"opened via '{reward_title}' redeem")
        if isinstance(result, str):
            log.warning("redeem-triggered ticket failed for %s: %s", discord_user_id, result)

    else:
        log.error("unknown redeem action type %r for '%s' in guild %s", action_type, reward_title, guild_id)
