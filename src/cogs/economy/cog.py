from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs.economy import db as economy_db
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("economy.cog")

WORK_COOLDOWN = 60 * 60          # 1h
DAILY_COOLDOWN = 60 * 60 * 24    # 24h

WORK_MIN, WORK_MAX = 50, 200
DAILY_MIN, DAILY_MAX = 200, 400

WORK_LINES = [
    "streamed for a bit and made {amt} coins in donations",
    "fixed a bug in prod and got paid {amt} coins",
    "moderated chat for an hour, earned {amt} coins",
    "sold some merch, {amt} coins richer",
]


def _fmt_cooldown(seconds_left: int) -> str:
    h, rem = divmod(seconds_left, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


class EconomyCog(commands.Cog, name="economy"):
    """coin economy - /work, /daily, /gamble, /balance, /leaderboard."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot

    @app_commands.command(name="balance", description="check your (or someone's) coin balance")
    @app_commands.describe(user="whose balance to check")
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        bal = await economy_db.get_balance(self.bot.db, interaction.guild_id, target.id)
        await interaction.response.send_message(f"{target.mention} has **{bal}** coins.")

    @app_commands.command(name="work", description="work for some coins (hourly cooldown)")
    async def work(self, interaction: discord.Interaction) -> None:
        guild_id, user_id = interaction.guild_id, interaction.user.id
        now = int(time.time())
        last = await economy_db.get_cooldown(self.bot.db, guild_id, user_id, "last_work")
        remaining = WORK_COOLDOWN - (now - last)
        if remaining > 0:
            await interaction.response.send_message(
                f"already worked recently, try again in {_fmt_cooldown(remaining)}.",
                ephemeral=True,
            )
            return

        amount = random.randint(WORK_MIN, WORK_MAX)
        await economy_db.set_cooldown(self.bot.db, guild_id, user_id, "last_work", now)
        new_bal = await economy_db.add_balance(self.bot.db, guild_id, user_id, amount)
        line = random.choice(WORK_LINES).format(amt=amount)
        await interaction.response.send_message(f"{line} - balance: **{new_bal}**")

    @app_commands.command(name="daily", description="claim your daily coins")
    async def daily(self, interaction: discord.Interaction) -> None:
        guild_id, user_id = interaction.guild_id, interaction.user.id
        now = int(time.time())
        last = await economy_db.get_cooldown(self.bot.db, guild_id, user_id, "last_daily")
        remaining = DAILY_COOLDOWN - (now - last)
        if remaining > 0:
            await interaction.response.send_message(
                f"already claimed today, try again in {_fmt_cooldown(remaining)}.",
                ephemeral=True,
            )
            return

        amount = random.randint(DAILY_MIN, DAILY_MAX)
        await economy_db.set_cooldown(self.bot.db, guild_id, user_id, "last_daily", now)
        new_bal = await economy_db.add_balance(self.bot.db, guild_id, user_id, amount)
        await interaction.response.send_message(f"claimed your daily **{amount}** coins - balance: **{new_bal}**")

    @app_commands.command(name="gamble", description="gamble coins on a coinflip")
    @app_commands.describe(amount="how many coins to bet")
    async def gamble(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, None]) -> None:
        guild_id, user_id = interaction.guild_id, interaction.user.id
        bal = await economy_db.get_balance(self.bot.db, guild_id, user_id)
        if amount > bal:
            await interaction.response.send_message(
                f"you only have **{bal}** coins.", ephemeral=True
            )
            return

        won = random.random() < 0.5
        delta = amount if won else -amount
        new_bal = await economy_db.add_balance(self.bot.db, guild_id, user_id, delta)
        outcome = f"won **{amount}**" if won else f"lost **{amount}**"
        await interaction.response.send_message(f"coin flip... {outcome} - balance: **{new_bal}**")

    @app_commands.command(name="leaderboard", description="top coin balances in this server")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = await economy_db.get_leaderboard(self.bot.db, interaction.guild_id)
        if not rows:
            await interaction.response.send_message("nobody's earned anything yet.")
            return

        lines = []
        for i, (user_id, balance) in enumerate(rows, start=1):
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            name = member.display_name if member else f"<@{user_id}>"
            lines.append(f"{i}. {name} - {balance}")
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: "Bot") -> None:
    await bot.add_cog(EconomyCog(bot))
