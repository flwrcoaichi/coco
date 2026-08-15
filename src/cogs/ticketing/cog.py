from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui
from discord.ext import commands

from src.cogs.ticketing.db import (
    close_ticket,
    create_panel,
    create_ticket,
    get_open_ticket_for,
    get_panel,
    get_ticket_by_channel,
    set_panel_message,
)
from src.utils.ui import BaseLayout, BaseModal
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("ticketing")

def _panel_layout(title: str, description: str, panel_id: int) -> BaseLayout:
    layout = BaseLayout()
    layout.add_container(ui.TextDisplay(f"# {title}\n{description}"), accent_color=0x5865F2)
    layout.add_item(ui.ActionRow(OpenTicketButton(panel_id)))
    return layout


async def _resolve_open_ticket(bot: "Bot", guild: discord.Guild, opener_id: int) -> dict[str, object] | None:
    """returns the opener's open ticket, or None - and quietly closes the DB
    record if the thread it points to is gone (deleted, or from before this
    feature existed and pointed at a since-deleted text channel)."""
    existing = await get_open_ticket_for(bot.db, guild.id, opener_id)  # type: ignore[attr-defined]
    if existing is None:
        return None
    channel = guild.get_channel_or_thread(int(existing["channel_id"]))  # type: ignore[arg-type]
    if channel is None:
        await close_ticket(bot.db, int(existing["channel_id"]))  # type: ignore[attr-defined]
        return None
    if isinstance(channel, discord.Thread) and channel.archived:
        await close_ticket(bot.db, int(existing["channel_id"]))  # type: ignore[attr-defined]
        return None
    return existing


async def open_ticket_for(
    bot: "Bot", guild: discord.Guild, panel_id: int, member: discord.Member, reason: str = ""
) -> discord.Thread | str:
    """opens a ticket thread for `member` under whatever panel `panel_id`
    points to. returns the thread, or an error string on failure. shared by
    the "open ticket" button flow and anything else that wants to open one
    programmatically (e.g. a twitch redeem action)."""
    panel = await get_panel(bot.db, panel_id)  # type: ignore[attr-defined]
    if panel is None:
        return "that ticket panel no longer exists"

    existing = await _resolve_open_ticket(bot, guild, member.id)  # type: ignore[arg-type]
    if existing is not None:
        return f"already has an open ticket: <#{existing['channel_id']}>"

    parent = guild.get_channel(int(panel["channel_id"]))  # type: ignore[arg-type]
    if not isinstance(parent, discord.TextChannel):
        return "the ticket channel for this panel is missing"

    display_name = member.name or str(member.id)
    thread_name = f"ticket-{display_name}"[:90]

    try:
        thread = await parent.create_thread(
            name=thread_name,
            type=discord.ChannelType.private_thread,
            invitable=False,
            reason=f"ticket opened for {member}",
        )
    except discord.HTTPException as e:
        return f"couldn't open a ticket thread: {e}"

    await create_ticket(bot.db, guild.id, thread.id, member.id, panel_id, reason)  # type: ignore[attr-defined]
    await thread.add_user(member)

    staff_role_id = int(panel["staff_role_id"]) if panel["staff_role_id"] else 0  # type: ignore[arg-type]
    staff_mention = f"<@&{staff_role_id}> - " if staff_role_id else ""

    layout = BaseLayout()
    layout.add_container(
        ui.TextDisplay(
            f"# ticket opened\n{staff_mention}{member.mention} - a member of staff will be with you shortly.\n\n"
            f"**Reason:** {reason or 'no reason provided'}"
        ),
        accent_color=0x57F287,
    )
    layout.add_item(ui.ActionRow(CloseTicketButton()))
    await thread.send(view=layout)
    log.info("ticket opened for %s in thread %s", member.id, thread.id)
    return thread


class TicketReasonModal(BaseModal):
    reason = ui.TextInput(
        label="Reason for support",
        placeholder="Describe your issue or question",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=512,
    )

    def __init__(self, panel_id: int, user: discord.User) -> None:
        super().__init__(title="Ticket reason", custom_id=f"ticket_reason_modal:{panel_id}:{user.id}")
        self.panel_id = panel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        bot = interaction.client
        await interaction.response.defer(ephemeral=True)
        result = await open_ticket_for(bot, interaction.guild, self.panel_id, interaction.user, self.reason.value.strip())  # type: ignore[arg-type]
        if isinstance(result, str):
            await interaction.followup.send(result, ephemeral=True)
            return
        await interaction.followup.send(f"ticket created: {result.mention}", ephemeral=True)


class OpenTicketButton(ui.DynamicItem[ui.Button[ui.View]], template=r"ticket:open:(\d+)"):
    def __init__(self, panel_id: int) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label="open ticket",
            style=discord.ButtonStyle.primary,
            custom_id=f"ticket:open:{panel_id}",
        )
        super().__init__(item)
        self.panel_id = panel_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "OpenTicketButton":
        return cls(int(match.group(1)))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        modal = TicketReasonModal(self.panel_id, interaction.user)
        await interaction.response.send_modal(modal)


class CloseTicketButton(ui.DynamicItem[ui.Button[ui.View]], template=r"ticket:close"):
    def __init__(self) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label="close ticket", style=discord.ButtonStyle.danger, custom_id="ticket:close"
        )
        super().__init__(item)

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "CloseTicketButton":
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if interaction.guild is None or not isinstance(interaction.channel, discord.Thread):
            return
        ticket = await get_ticket_by_channel(bot.db, interaction.channel.id)  # type: ignore[attr-defined]
        if ticket is None:
            await interaction.response.send_message("this isn't a ticket thread", ephemeral=True)
            return
        await close_ticket(bot.db, interaction.channel.id)  # type: ignore[attr-defined]
        await interaction.response.send_message("closing this ticket...")
        await interaction.channel.edit(archived=True, locked=True, reason="ticket closed")


class TicketingCog(commands.Cog, name="ticketing"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        bot.add_dynamic_items(OpenTicketButton, CloseTicketButton)

    ticket = app_commands.Group(
        name="ticket", description="ticketing system", default_permissions=discord.Permissions(manage_guild=True)
    )

    @ticket.command(name="panel", description="post a ticket panel - tickets open as private threads under this channel")
    @app_commands.describe(
        channel="channel new ticket threads open under",
        staff_role="role pinged and auto-added to every ticket",
        title="panel title",
        description="panel description",
    )
    async def panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        staff_role: discord.Role | None = None,
        title: str = "support",
        description: str = "click below to open a ticket",
    ) -> None:
        if interaction.guild is None:
            return
        panel_id = await create_panel(
            self.bot.db,
            interaction.guild.id,
            channel.id,
            0,
            staff_role.id if staff_role else 0,
            title,
            description,
        )
        layout = _panel_layout(title, description, panel_id)
        msg = await channel.send(view=layout)
        await set_panel_message(self.bot.db, panel_id, msg.id)
        await interaction.response.send_message(f"panel posted in {channel.mention}", ephemeral=True)

    @ticket.command(name="close", description="close the current ticket")
    async def close(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("this isn't a ticket thread", ephemeral=True)
            return
        ticket = await get_ticket_by_channel(self.bot.db, interaction.channel.id)
        if ticket is None:
            await interaction.response.send_message("this isn't a ticket thread", ephemeral=True)
            return
        await close_ticket(self.bot.db, interaction.channel.id)
        await interaction.response.send_message("closing this ticket...")
        await interaction.channel.edit(archived=True, locked=True, reason="ticket closed")

    @ticket.command(name="add", description="add a member to the current ticket")
    @app_commands.describe(member="member to add")
    async def add(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("this isn't a ticket thread", ephemeral=True)
            return
        ticket = await get_ticket_by_channel(self.bot.db, interaction.channel.id)
        if ticket is None:
            await interaction.response.send_message("this isn't a ticket thread", ephemeral=True)
            return
        await interaction.channel.add_user(member)
        await interaction.response.send_message(f"added {member.mention} to the ticket")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(TicketingCog(bot))

