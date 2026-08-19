from __future__ import annotations

import json
import secrets
from typing import Any

from src.data.db import Database

VALID_STYLES = ("primary", "secondary", "success", "danger")


def new_item_id() -> str:
    return secrets.token_hex(4)


async def get_containers(db: Database, guild_id: int) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "select name, created_by, items, accent_color from button_containers where guild_id = ? order by name",
        (guild_id,),
    )
    out: list[dict[str, Any]] = []
    for name, created_by, items, accent_color in rows:
        try:
            parsed_items = json.loads(str(items))
        except json.JSONDecodeError:
            parsed_items = []
        out.append(
            {
                "name": name,
                "created_by": created_by,
                "items": parsed_items,
                "accent_color": accent_color,
            }
        )
    return out


async def save_container(
    db: Database,
    guild_id: int,
    name: str,
    created_by: int,
    items: list[dict[str, Any]],
    accent_color: int | None,
) -> None:
    await db.execute(
        "insert into button_containers (guild_id, name, created_by, items, accent_color)"
        " values (?, ?, ?, ?, ?)"
        " on conflict (guild_id, name) do update set"
        " items = excluded.items, accent_color = excluded.accent_color, created_by = excluded.created_by",
        (guild_id, name, created_by, json.dumps(items), accent_color),
    )


async def delete_container(db: Database, guild_id: int, name: str) -> None:
    await db.execute(
        "delete from button_containers where guild_id = ? and name = ?", (guild_id, name)
    )


async def get_container(db: Database, guild_id: int, name: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "select name, created_by, items, accent_color from button_containers"
        " where guild_id = ? and name = ?",
        (guild_id, name),
    )
    if row is None:
        return None
    name_, created_by, items, accent_color = row
    try:
        parsed_items = json.loads(str(items))
    except json.JSONDecodeError:
        parsed_items = []
    return {
        "name": name_,
        "created_by": created_by,
        "items": parsed_items,
        "accent_color": accent_color,
    }


async def get_container_item(
    db: Database, guild_id: int, container_name: str, item_id: str
) -> dict[str, Any] | None:
    """look up a single button's config fresh from the db, so edits to a
    container apply immediately to already-posted messages without repost."""
    container = await get_container(db, guild_id, container_name)
    if container is None:
        return None
    for item in container["items"]:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


async def find_item_by_id(db: Database, guild_id: int, item_id: str) -> dict[str, Any] | None:
    """finds a button by its item id alone, without needing the container
    name. item ids are random per-guild tokens assigned by new_item_id, so
    this is used to keep custom_ids short (they only need to encode item_id,
    not the container's name, which may be long)."""
    containers = await get_containers(db, guild_id)
    for container in containers:
        for item in container["items"]:
            if isinstance(item, dict) and item.get("id") == item_id:
                return item
    return None


async def add_item(
    db: Database,
    guild_id: int,
    container_name: str,
    created_by: int,
    *,
    label: str,
    style: str,
    action: str,
    data: dict[str, Any],
) -> str:
    """append a button to a container, creating the container if needed.
    returns the new item's id."""
    container = await get_container(db, guild_id, container_name)
    items: list[dict[str, Any]] = container["items"] if container else []
    accent_color = container["accent_color"] if container else None
    item_id = new_item_id()
    items.append(
        {"id": item_id, "label": label, "style": style, "action": action, "data": data}
    )
    await save_container(db, guild_id, container_name, created_by, items, accent_color)
    return item_id


async def remove_item(db: Database, guild_id: int, container_name: str, item_id: str) -> bool:
    """removes a single button from a container. returns True if it was found."""
    container = await get_container(db, guild_id, container_name)
    if container is None:
        return False
    items = [i for i in container["items"] if not (isinstance(i, dict) and i.get("id") == item_id)]
    if len(items) == len(container["items"]):
        return False
    await save_container(
        db, guild_id, container_name, container["created_by"], items, container["accent_color"]
    )
    return True
