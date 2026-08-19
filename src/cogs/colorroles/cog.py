from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.data.db import Database
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("colorroles.cog")

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_MARKER_ROLE_NAME = "colors:"

    
async def _get_saved_role_id(db: Database, guild_id: int, user_id: int) -> int | None:
    row = await db.fetchone(
        "select role_id from color_roles where guild_id = ? and user_id = ?",
        (guild_id, user_id),
    )
    return int(row[0]) if row else None


async def _save_role_id(db: Database, guild_id: int, user_id: int, role_id: int) -> None:
    await db.execute(
        "insert into color_roles (guild_id, user_id, role_id) values (?, ?, ?)"
        " on conflict(guild_id, user_id) do update set role_id = excluded.role_id",
        (guild_id, user_id, role_id),
    )


async def _clear_saved_role_id(db: Database, guild_id: int, user_id: int) -> None:
    await db.execute(
        "delete from color_roles where guild_id = ? and user_id = ?", (guild_id, user_id)
    )


class ColorRolesCog(commands.Cog, name="colorroles"):
    """lets members set a personal, uniquely-colored role by hex code.
    the role is created just below a marker role named exactly `colors:`
    in the server's role list - create that marker role once per server
    and keep it above the @everyone / regular member roles you want the
    color to show up over.
    """

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot

    async def _get_existing_role(self, member: discord.Member) -> discord.Role | None:
        role_id = await _get_saved_role_id(self.bot.db, member.guild.id, member.id)
        if role_id is None:
            return None
        role = member.guild.get_role(role_id)
        if role is None:
            await _clear_saved_role_id(self.bot.db, member.guild.id, member.id)
        return role

    @commands.hybrid_command(name="color", aliases=["colour"], description="set or remove your personal color role")
    async def color_cmd(self, ctx: commands.Context, hex_or_remove: str = "") -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("this command only works in a server")
            return
        guild = ctx.guild
        member = ctx.author

        if hex_or_remove.lower() in ("remove", "-r", "none", "clear"):
            old_role = await self._get_existing_role(member)
            if old_role is None:
                await ctx.send("you don't have a color role")
                return
            await member.remove_roles(old_role)
            await old_role.delete(reason=f"color removed by {member}")
            await _clear_saved_role_id(self.bot.db, guild.id, member.id)
            await ctx.send("removed your color role")
            return

        if not hex_or_remove:
            await ctx.send("usage: `>color #RRGGBB` or `>color remove`")
            return

        hex_match = _HEX_RE.match(hex_or_remove)
        if not hex_match:
            await ctx.send("invalid hex color - use the format `#rrggbb` or `rrggbb`")
            return
        hex_code = hex_match.group(1).upper()
        color_value = int(hex_code, 16)

        marker = discord.utils.get(guild.roles, name=_MARKER_ROLE_NAME)
        if not marker:
            await ctx.send(
                f"no `{_MARKER_ROLE_NAME}` marker role found - create one (any color/permissions,"
                " position it above the roles you want colors to outrank) and try again"
            )
            return

        old_role = await self._get_existing_role(member)
        if old_role is not None:
            await old_role.delete(reason=f"replacing color for {member}")

        new_role = await guild.create_role(
            name=f"{member.display_name} | {hex_code}",
            color=discord.Color(color_value),
            reason=f"custom color for {member}",
        )
        try:
            await new_role.edit(position=marker.position - 1)
        except discord.HTTPException:
            log.warning("couldn't reposition color role for %s", member)

        await member.add_roles(new_role)
        await _save_role_id(self.bot.db, guild.id, member.id, new_role.id)
        await ctx.send(f"set your color to #{hex_code}")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(ColorRolesCog(bot))
