from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord

ActionHandler = Callable[[discord.Interaction, dict[str, Any]], Awaitable[None]]

_HANDLERS: dict[str, ActionHandler] = {}


def action(name: str) -> Callable[[ActionHandler], ActionHandler]:
    """decorator to register a button action handler under `name`."""

    def wrapper(fn: ActionHandler) -> ActionHandler:
        _HANDLERS[name] = fn
        return fn

    return wrapper


def get_handler(name: str) -> ActionHandler | None:
    return _HANDLERS.get(name)


def available_actions() -> list[str]:
    return sorted(_HANDLERS.keys())


@action("grant_role")
async def _grant_role(interaction: discord.Interaction, data: dict[str, Any]) -> None:
    """toggles a role on the clicking member. data: {"role_id": int}"""
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("this only works in a server", ephemeral=True)
        return
    role_id = data.get("role_id")
    if not isinstance(role_id, int):
        await interaction.response.send_message("this button is misconfigured (no role set)", ephemeral=True)
        return
    role = interaction.guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message("that role no longer exists", ephemeral=True)
        return
    try:
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="button role toggle")
            await interaction.response.send_message(f"removed **{role.name}**", ephemeral=True)
        else:
            await interaction.user.add_roles(role, reason="button role toggle")
            await interaction.response.send_message(f"added **{role.name}**", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message(
            "couldn't update your roles - check my role is above the target role", ephemeral=True
        )


@action("give_role")
async def _give_role(interaction: discord.Interaction, data: dict[str, Any]) -> None:
    """non-toggling grant, for verify-style buttons where clicking again should
    just no-op rather than remove the role. data: {"role_id": int}"""
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("this only works in a server", ephemeral=True)
        return
    role_id = data.get("role_id")
    if not isinstance(role_id, int):
        await interaction.response.send_message("this button is misconfigured (no role set)", ephemeral=True)
        return
    role = interaction.guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message("that role no longer exists", ephemeral=True)
        return
    if role in interaction.user.roles:
        await interaction.response.send_message(f"you already have **{role.name}**", ephemeral=True)
        return
    try:
        await interaction.user.add_roles(role, reason="button verify")
        await interaction.response.send_message(f"verified - you now have **{role.name}**", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message(
            "couldn't add the role - check my role is above the target role", ephemeral=True
        )
