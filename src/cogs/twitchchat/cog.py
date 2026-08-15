from __future__ import annotations

from ast import arg
import random
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import string

from src.cogs.economy import db as economy_db
from src.cogs.economy import links as economy_links
from src.cogs.twitchchat.db import (
    add_command,
    add_watchtime,
    clear_queue,
    get_command,
    get_settings,
    get_watchtime,
    list_commands,
    list_queue,
    list_shoutout_overrides,
    queue_join,
    remove_command,
    remove_shoutout_override,
    set_channel,
    set_enabled,
    set_shoutout_override,
    get_shoutout_override,
    upsert_settings,
)
from src.cogs.twitchchat.irc import TWITCH_BOT_USERNAME, ChatMessage, TwitchIRCClient
from src.cogs.twitchchat.oauth import TwitchAuthServer, get_valid_access_token
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitchchat.cog")

_REMINDERS = {
    "!hydrate": "time to drink some water! 💧",
    "!stretch": "stand up and stretch for a sec 🧍",
    "!posture": "check your posture - shoulders back!",
}
CHECKIN_COOLDOWN = 60 * 60
CHECKIN_MIN, CHECKIN_MAX = 20, 60
_WATCHTIME_GAP_CAP = 120


class TwitchChatCog(commands.Cog, name="twitchchat"):
    """a twitch chat bot (separate from the EventSub live-notification cog)
    that joins tracked streamers' channels as a bot account (e.g. cocoFLWR),
    the same way StreamElements/Nightbot do - the streamer adds it as a mod,
    no per-streamer OAuth needed for chat itself. see README_INTEGRATION.md.
    """

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self.irc = TwitchIRCClient(self._on_message, self._get_token)
        self.auth_server = TwitchAuthServer(bot)
        self._last_seen: dict[tuple[int, str], float] = {}
        self._pending_links: dict[str, tuple[int, int, float]] = {}

    async def _get_token(self) -> str | None:
        return await get_valid_access_token(self.bot)

    async def cog_load(self) -> None:
        await self.auth_server.start()
        await self.irc.start()
        settings = await self.bot.db.fetchall(
            "select guild_id, twitch_channel from twitch_chat_settings where enabled = 1"
        )
        for guild_id, channel in settings:
            if channel:
                await self.irc.join(str(channel))

    async def cog_unload(self) -> None:
        await self.irc.stop()
        await self.auth_server.stop()

    # ---- config commands ----

    group = discord.app_commands.Group(name="twitchchat", description="configure the twitch chat bot")

    @group.command(name="setup", description="join a twitch channel with the chat bot")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def setup_cmd(self, interaction: discord.Interaction, channel: str) -> None:
        token = await get_valid_access_token(self.bot)
        if token is None:
            await interaction.response.send_message(
                "authentication error.",
                ephemeral=True,
            )
            return
        assert interaction.guild is not None
        await set_channel(self.bot.db, interaction.guild.id, channel)
        await self.irc.join(channel)
        await interaction.response.send_message(
            f"joined **#{channel.lower()}** - make sure the bot account is modded there.",
            ephemeral=True,
        )
    @group.command(name="link", description="link your discord account to your twitch account")
    async def link(self, interaction: discord.Interaction) -> None:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        expires_at = time.monotonic() + 300
        self._pending_links[code] = (interaction.guild_id, interaction.user.id, expires_at)
        await interaction.response.send_message(
            f"type `!link {code}` in twitch chat within 5 minutes to link your account.",
            ephemeral=True,
        )

    @group.command(name="unlink", description="unlink your discord account from twitch")
    async def unlink(self, interaction: discord.Interaction) -> None:
        await economy_links.unlink_account(self.bot.db, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message("unlinked.", ephemeral=True)

    @group.command(name="subonly", description="restrict custom/random commands to subscribers")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def subonly_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild is not None
        await upsert_settings(self.bot.db, interaction.guild.id, sub_only=1 if enabled else 0)
        await interaction.response.send_message(f"sub-only mode: {enabled}", ephemeral=True)

    @group.command(name="shoutoutchannel", description="discord channel for !so/!shoutout posts")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def shoutout_channel_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        assert interaction.guild is not None
        await upsert_settings(self.bot.db, interaction.guild.id, shoutout_channel_id=channel.id)
        await interaction.response.send_message(f"shoutouts will post to {channel.mention}", ephemeral=True)

    @group.command(name="shoutoutmessage", description="default !so message. placeholders: {user} {game} {url}")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def shoutout_message_cmd(self, interaction: discord.Interaction, message: str) -> None:
        assert interaction.guild is not None
        await upsert_settings(self.bot.db, interaction.guild.id, shoutout_message=message)
        await interaction.response.send_message(f"default shoutout message set to:\n{message}", ephemeral=True)

    shoutout_group = discord.app_commands.Group(
        name="shoutoutfor", description="per-streamer !so message overrides"
    )

    @shoutout_group.command(name="set", description="set a custom !so message for one twitch user")
    @discord.app_commands.describe(
        twitch_user="twitch username this override applies to",
        message="placeholders: {user} {game} {url}",
    )
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def shoutout_for_set(
        self, interaction: discord.Interaction, twitch_user: str, message: str
    ) -> None:
        assert interaction.guild is not None
        await set_shoutout_override(self.bot.db, interaction.guild.id, twitch_user, message)
        await interaction.response.send_message(
            f"`!so {twitch_user}` will now say:\n{message}", ephemeral=True
        )

    @shoutout_group.command(name="remove", description="remove a per-streamer !so override")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def shoutout_for_remove(self, interaction: discord.Interaction, twitch_user: str) -> None:
        assert interaction.guild is not None
        await remove_shoutout_override(self.bot.db, interaction.guild.id, twitch_user)
        await interaction.response.send_message(f"removed the override for {twitch_user}", ephemeral=True)

    @shoutout_group.command(name="list", description="list all per-streamer !so overrides")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def shoutout_for_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        overrides = await list_shoutout_overrides(self.bot.db, interaction.guild.id)
        if not overrides:
            await interaction.response.send_message("no per-streamer overrides set", ephemeral=True)
            return
        lines = [f"**{o['twitch_login']}**: {o['message']}" for o in overrides]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @group.command(name="clipchannel", description="discord channel for !clip posts")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def clip_channel_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        assert interaction.guild is not None
        await upsert_settings(self.bot.db, interaction.guild.id, clip_channel_id=channel.id)
        await interaction.response.send_message(f"clips will post to {channel.mention}", ephemeral=True)

    @group.command(name="owner", description="who !hydrate/!stretch/!posture DM reminders go to")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def owner_cmd(self, interaction: discord.Interaction, user: discord.User) -> None:
        assert interaction.guild is not None
        await upsert_settings(self.bot.db, interaction.guild.id, owner_discord_id=user.id)
        await interaction.response.send_message(f"reminders will DM {user.mention}", ephemeral=True)

    @group.command(name="queue", description="show or clear the !join/!queue list")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def queue_cmd(self, interaction: discord.Interaction, clear: bool = False) -> None:
        assert interaction.guild is not None
        if clear:
            await clear_queue(self.bot.db, interaction.guild.id)
            await interaction.response.send_message("queue cleared", ephemeral=True)
            return
        entries = await list_queue(self.bot.db, interaction.guild.id)
        text = ", ".join(entries) if entries else "(empty)"
        await interaction.response.send_message(f"queue: {text}", ephemeral=True)

    cmd_group = discord.app_commands.Group(
        name="twitchcmd", description="manage custom !commands for the twitch chat bot"
    )

    @cmd_group.command(name="add", description="add a random-roll command, e.g. !luck {user} has {random}% luck")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_add(
        self,
        interaction: discord.Interaction,
        trigger: str,
        template: str,
        min_roll: int = 0,
        max_roll: int = 100,
    ) -> None:
        assert interaction.guild is not None
        kind = "random" if "{random}" in template else "text"
        await add_command(self.bot.db, interaction.guild.id, trigger, template, kind, min_roll, max_roll)
        await interaction.response.send_message(f"added `{trigger}`", ephemeral=True)

    @cmd_group.command(name="remove", description="remove a custom command")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_remove(self, interaction: discord.Interaction, trigger: str) -> None:
        assert interaction.guild is not None
        await remove_command(self.bot.db, interaction.guild.id, trigger)
        await interaction.response.send_message(f"removed `{trigger}`", ephemeral=True)

    @cmd_group.command(name="list", description="list custom commands")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        cmds = await list_commands(self.bot.db, interaction.guild.id)
        if not cmds:
            await interaction.response.send_message("no custom commands yet", ephemeral=True)
            return
        lines = [f"`{c['trigger']}` → {c['template']}" for c in cmds]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ---- chat message handling ----
    async def _cmd_link(self, guild_id: int, msg: ChatMessage, arg: str) -> None:
        code = arg.strip().upper()
        pending = self._pending_links.get(code)
        if pending is None:
            await self._reply(msg.channel, f"@{msg.user_login} that code isn't valid, run /twitchchat link again")
            return
        pend_guild_id, discord_user_id, expires_at = pending
        if pend_guild_id != guild_id or time.monotonic() > expires_at:
            del self._pending_links[code]
            await self._reply(msg.channel, f"@{msg.user_login} that code expired, run /twitchchat link again")
            return

        del self._pending_links[code]
        await economy_links.link_account(self.bot.db, guild_id, discord_user_id, msg.user_login, int(time.time()))

        # merge: fold any existing twitch-only balance into the discord balance
        twitch_bal = await economy_db.get_twitch_balance(self.bot.db, guild_id, msg.user_login)
        if twitch_bal:
            await economy_db.add_balance(self.bot.db, guild_id, discord_user_id, twitch_bal)
            await economy_db.add_twitch_balance(self.bot.db, guild_id, msg.user_login, -twitch_bal)

        await self._reply(msg.channel, f"@{msg.user_login} linked! your coins now carry over between discord and chat.")

    async def _resolve_economy_id(self, guild_id: int, login: str) -> int | None:
        """returns a discord user id if this twitch login is linked, else None."""
        return await economy_links.get_discord_user_id(self.bot.db, guild_id, login)

    async def _cmd_checkin(self, guild_id: int, msg: ChatMessage) -> None:
        now = int(time.time())
        discord_id = await self._resolve_economy_id(guild_id, msg.user_login)
        last = await economy_db.get_twitch_checkin(self.bot.db, guild_id, msg.user_login)
        remaining = CHECKIN_COOLDOWN - (now - last)
        if remaining > 0:
            m, s = divmod(remaining, 60)
            await self._reply(msg.channel, f"@{msg.user_login} already checked in, try again in {m}m {s}s")
            return
        amount = random.randint(CHECKIN_MIN, CHECKIN_MAX)
        await economy_db.set_twitch_checkin(self.bot.db, guild_id, msg.user_login, now)
        if discord_id is not None:
            new_bal = await economy_db.add_balance(self.bot.db, guild_id, discord_id, amount)
        else:
            new_bal = await economy_db.add_twitch_balance(self.bot.db, guild_id, msg.user_login, amount)
        await self._reply(msg.channel, f"@{msg.user_login} checked in for {amount} coins ----- balance: {new_bal}")

    async def _cmd_gamble(self, guild_id: int, msg: ChatMessage, arg: str) -> None:
        discord_id = await self._resolve_economy_id(guild_id, msg.user_login)
        if discord_id is not None:
            bal = await economy_db.get_balance(self.bot.db, guild_id, discord_id)
        else:
            bal = await economy_db.get_twitch_balance(self.bot.db, guild_id, msg.user_login)
        try:
            amount = int(arg.strip())
        except ValueError:
            await self._reply(msg.channel, f"@{msg.user_login} usage: !gamble <amount>")
            return
        if amount <= 0 or amount > bal:
            await self._reply(msg.channel, f"@{msg.user_login} you only have {bal} coins")
            return
        won = random.random() < 0.5
        delta = amount if won else -amount
        if discord_id is not None:
            new_bal = await economy_db.add_balance(self.bot.db, guild_id, discord_id, delta)
        else:
            new_bal = await economy_db.add_twitch_balance(self.bot.db, guild_id, msg.user_login, delta)
        outcome = f"won {amount}" if won else f"lost {amount}"
        await self._reply(msg.channel, f"@{msg.user_login} coin flip... {outcome} ----- balance: {new_bal}")

    async def _cmd_balance(self, guild_id: int, msg: ChatMessage) -> None:
        discord_id = await self._resolve_economy_id(guild_id, msg.user_login)
        if discord_id is not None:
            bal = await economy_db.get_balance(self.bot.db, guild_id, discord_id)
        else:
            bal = await economy_db.get_twitch_balance(self.bot.db, guild_id, msg.user_login)
        await self._reply(msg.channel, f"@{msg.user_login} has {bal} coins")
    async def _guild_for_channel(self, channel: str) -> tuple[int, dict[str, object]] | None:
        row = await self.bot.db.fetchone(
            "select guild_id from twitch_chat_settings where twitch_channel = ? and enabled = 1",
            (channel.lower(),),
        )
        if row is None:
            return None
        guild_id = int(row[0])
        settings = await get_settings(self.bot.db, guild_id)
        assert settings is not None
        return guild_id, settings

    async def _on_message(self, msg: ChatMessage) -> None:
        if msg.is_foreign:
            return
        found = await self._guild_for_channel(msg.channel)
        if found is None:
            return
        guild_id, settings = found
        
        # watchtime: credit elapsed time since this user's last message,
        # capped so idling doesn't inflate it.
        key = (guild_id, msg.user_login)
        now = time.monotonic()
        last = self._last_seen.get(key)
        if last is not None:
            elapsed = min(now - last, _WATCHTIME_GAP_CAP)
            await add_watchtime(self.bot.db, guild_id, msg.user_login, int(elapsed))
        self._last_seen[key] = now

        if not msg.text.startswith("!"):
            return
        parts = msg.text.split(None, 1)
        trigger = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if trigger in ("!so", "!shoutout"):
            if not (msg.is_mod or msg.is_broadcaster):
                return
            await self._cmd_shoutout(guild_id, settings, msg, arg)
        elif trigger == "!clip":
            if not (msg.is_mod or msg.is_broadcaster):
                return
            await self._cmd_clip(guild_id, settings, msg)
        elif trigger == "!link":
            await self._cmd_link(guild_id, msg, arg)
        elif trigger == "!followage":
            await self._cmd_followage(guild_id, settings, msg, arg or msg.user_login)
        elif trigger == "!watchtime":
            await self._cmd_watchtime(guild_id, msg, arg or msg.user_login)
        elif trigger in _REMINDERS:
            await self._cmd_reminder(guild_id, settings, trigger)
        elif trigger in ("!join", "!queue"):
            await self._cmd_join(guild_id, msg)
        elif trigger == "!checkin":
            await self._cmd_checkin(guild_id, msg)
        elif trigger == "!gamble":
            await self._cmd_gamble(guild_id, msg, arg)
        elif trigger == "!balance":
            await self._cmd_balance(guild_id, msg)
        else:
            await self._cmd_custom(guild_id, settings, msg, trigger, arg)

    async def _reply(self, channel: str, text: str) -> None:
        await self.irc.send(channel, text)

    async def _cmd_shoutout(
        self, guild_id: int, settings: dict[str, object], msg: ChatMessage, arg: str
    ) -> None:
        target = arg.lstrip("@").strip() or msg.user_login
        result = await self.bot.twitch.get_user_id(target)
        if result is None:
            await self._reply(msg.channel, f"couldn't find twitch user '{target}'")
            return
        user_id, display_name = result
        info = await self.bot.twitch.get_channel_info(user_id)
        game = info["game_name"] if info and info.get("game_name") else "something"
        url = f"https://twitch.tv/{target.lower()}"
        override = await get_shoutout_override(self.bot.db, guild_id, target)
        template = override or str(settings.get("shoutout_message") or "")
        text = template.replace("{user}", display_name).replace("{game}", game).replace("{url}", url)
        await self._reply(msg.channel, text)

        channel_id = int(settings.get("shoutout_channel_id") or 0)
        if channel_id:
            discord_channel = self.bot.get_channel(channel_id)
            if isinstance(discord_channel, discord.TextChannel):
                embed = discord.Embed(description=text, color=discord.Color.purple())
                embed.set_author(name=display_name, url=url)
                await discord_channel.send(embed=embed)

    async def _cmd_clip(self, guild_id: int, settings: dict[str, object], msg: ChatMessage) -> None:
        token = await get_valid_access_token(self.bot)
        if token is None:
            return
        result = await self.bot.twitch.get_user_id(msg.channel)
        if result is None:
            return
        broadcaster_id, _ = result
        url = await self.bot.twitch.create_clip(broadcaster_id, token)
        if url is None:
            await self._reply(
                msg.channel,
                "couldn't create a clip - make sure the bot is an editor on this channel",
            )
            return
        await self._reply(msg.channel, f"clipped it! {url}")

        channel_id = int(settings.get("clip_channel_id") or 0)
        if channel_id:
            discord_channel = self.bot.get_channel(channel_id)
            if isinstance(discord_channel, discord.TextChannel):
                await discord_channel.send(f"new clip from **{msg.channel}**: {url}")

    async def _cmd_followage(
        self, guild_id: int, settings: dict[str, object], msg: ChatMessage, target_login: str
    ) -> None:
        token = await get_valid_access_token(self.bot)
        if token is None:
            return
        broadcaster = await self.bot.twitch.get_user_id(msg.channel)
        user = await self.bot.twitch.get_user_id(target_login)
        mod = await self.bot.twitch.get_user_id(TWITCH_BOT_USERNAME)
        if broadcaster is None or user is None or mod is None:
            return
        followed_at = await self.bot.twitch.get_followage(broadcaster[0], user[0], mod[0], token)
        if followed_at is None:
            await self._reply(msg.channel, f"{user[1]} is not following.")
            return
        await self._reply(msg.channel, f"{user[1]} has been following since {followed_at[:10]}.")

    async def _cmd_watchtime(self, guild_id: int, msg: ChatMessage, target_login: str) -> None:
        seconds = await get_watchtime(self.bot.db, guild_id, target_login)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        await self._reply(msg.channel, f"{target_login} has watched for {hours}h {minutes}m.")

    async def _cmd_reminder(self, guild_id: int, settings: dict[str, object], trigger: str) -> None:
        owner_id = int(settings.get("owner_discord_id") or 0)
        if not owner_id:
            return
        user = self.bot.get_user(owner_id) or await self.bot.fetch_user(owner_id)
        try:
            await user.send(_REMINDERS[trigger])
        except discord.Forbidden:
            log.warning("couldn't DM owner %s for %s", owner_id, trigger)

    async def _cmd_join(self, guild_id: int, msg: ChatMessage) -> None:
        added = await queue_join(self.bot.db, guild_id, msg.user_login)
        if added:
            await self._reply(msg.channel, f"{msg.display_name} joined the queue!")
        else:
            await self._reply(msg.channel, f"{msg.display_name}, you're already in the queue.")

    async def _cmd_custom(
        self, guild_id: int, settings: dict[str, object], msg: ChatMessage, trigger: str, arg: str
    ) -> None:
        cmd = await get_command(self.bot.db, guild_id, trigger)
        if cmd is None:
            return
        if settings.get("sub_only") and not (msg.is_sub or msg.is_mod):
            return
        template = str(cmd["template"])
        text = template.replace("{user}", msg.display_name).replace("{arg}", arg)
        if cmd["kind"] == "random":
            roll = random.randint(int(cmd["min_roll"]), int(cmd["max_roll"]))
            text = text.replace("{random}", str(roll))
        await self._reply(msg.channel, text)


async def setup(bot: "Bot") -> None:
    cog = TwitchChatCog(bot)
    await bot.add_cog(cog)
