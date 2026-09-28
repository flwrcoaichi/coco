from __future__ import annotations

import re
from typing import Any

import discord
from discord import ui

from src.data.button_containers import find_item_by_id
from src.data.button_actions import get_handler
from src.utils.ui import BaseLayout

_STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}
DEFAULT_ACCENT = 0x5865F2


class ContainerButton(ui.DynamicItem[ui.Button[ui.View]], template=r"cm:c:(\d+):([A-Za-z0-9_-]+)"):
    def __init__(
        self,
        *,
        guild_id: int,
        container_name: str,
        item_id: str,
        label: str,
        style: discord.ButtonStyle,
        disabled: bool = False,
    ) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label=label,
            style=style,
            custom_id=f"cm:c:{guild_id}:{item_id}",
            disabled=disabled,
        )
        super().__init__(item)
        self.guild_id = guild_id
        self.container_name = container_name
        self.item_id = item_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "ContainerButton":
        return cls(
            guild_id=int(match.group(1)),
            container_name="",
            item_id=match.group(2),
            label=item.label or "click me",
            style=item.style,
            disabled=item.disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.item.disabled:
            return
        bot = interaction.client
        config = await find_item_by_id(bot.db, self.guild_id, self.item_id)  # type: ignore[attr-defined]
        if config is None:
            await interaction.response.send_message(
                "this button no longer exists (its container may have been edited or deleted)",
                ephemeral=True,
            )
            return
        handler = get_handler(config.get("action", ""))
        if handler is None:
            await interaction.response.send_message("this button isn't configured correctly", ephemeral=True)
            return
        await handler(interaction, config.get("data", {}) or {})


def _sequence(items: list[Any]) -> list[dict[str, Any] | str]:
    by_id = {str(i["id"]): i for i in items if isinstance(i, dict) and "id" in i}
    legacy = any(isinstance(i, dict) and i.get("type") == "display" for i in items)
    out: list[dict[str, Any] | str] = []
    for i in items:
        if not isinstance(i, dict):
            continue
        kind = i.get("type")
        if kind in ("separator", "break"):
            out.append(kind)
        elif kind == "display":
            ids = i.get("item_ids") or i.get("items") or []
            if isinstance(ids, str):
                ids = [p.strip() for p in ids.split(",") if p.strip()]
            out.extend(by_id[x] for x in ids if x in by_id)
        elif "id" in i and not legacy:
            out.append(i)
    return out


def _button(guild_id: int, container_name: str, raw: dict[str, Any]) -> ContainerButton:
    style_name = str(raw.get("style", "secondary"))
    disabled = str(raw.get("action", "")).lower() == "disabled"
    return ContainerButton(
        guild_id=guild_id,
        container_name=container_name,
        item_id=str(raw["id"]),
        label=str(raw.get("label") or "click me")[:80],
        style=_STYLE_MAP.get(style_name, discord.ButtonStyle.secondary),
        disabled=disabled,
    )


def build_container_layout(guild_id: int, container: dict[str, Any]) -> list[ui.Item]:
    out: list[ui.Item] = []
    row: ui.ActionRow | None = None

    def flush() -> None:
        nonlocal row
        if row is not None and row.children:
            out.append(row)
        row = None

    for entry in _sequence(container.get("items", [])):
        if entry == "separator":
            flush()
            if out and not isinstance(out[-1], ui.Separator):
                out.append(ui.Separator(spacing=discord.SeparatorSpacing.small))
            continue
        if entry == "break":
            flush()
            continue
        if row is not None and len(row.children) >= 5:
            flush()
        if row is None:
            row = ui.ActionRow()
        row.add_item(_button(guild_id, container["name"], entry))  # type: ignore[arg-type]
    flush()
    while out and isinstance(out[-1], ui.Separator):
        out.pop()
    return out


def build_container_rows(guild_id: int, container: dict[str, Any]) -> list[ui.ActionRow]:
    return [i for i in build_container_layout(guild_id, container) if isinstance(i, ui.ActionRow)]


def compose_message(guild_id: int, content: str, container: dict[str, Any] | None) -> BaseLayout:
    accent = DEFAULT_ACCENT
    if container and container.get("accent_color") is not None:
        accent = int(container["accent_color"])
    layout = BaseLayout()
    layout.add_container(ui.TextDisplay(content), accent_color=accent)
    if container:
        for item in build_container_layout(guild_id, container):
            layout.add_item(item)
    return layout
