from __future__ import annotations

from src.data.db import Database


async def get_balance(db: Database, guild_id: int, user_id: int) -> int:
    row = await db.fetchone(
        "select balance from economy_balances where guild_id = ? and user_id = ?",
        (guild_id, user_id),
    )
    return int(row[0]) if row else 0


async def _ensure_row(db: Database, guild_id: int, user_id: int) -> None:
    await db.execute(
        "insert into economy_balances (guild_id, user_id) values (?, ?)"
        " on conflict(guild_id, user_id) do nothing",
        (guild_id, user_id),
    )


async def add_balance(db: Database, guild_id: int, user_id: int, amount: int) -> int:
    await _ensure_row(db, guild_id, user_id)
    await db.execute(
        "update economy_balances set balance = balance + ? where guild_id = ? and user_id = ?",
        (amount, guild_id, user_id),
    )
    return await get_balance(db, guild_id, user_id)


async def get_cooldown(db: Database, guild_id: int, user_id: int, column: str) -> int:
    row = await db.fetchone(
        f"select {column} from economy_balances where guild_id = ? and user_id = ?",
        (guild_id, user_id),
    )
    return int(row[0]) if row else 0


async def set_cooldown(db: Database, guild_id: int, user_id: int, column: str, ts: int) -> None:
    await _ensure_row(db, guild_id, user_id)
    await db.execute(
        f"update economy_balances set {column} = ? where guild_id = ? and user_id = ?",
        (ts, guild_id, user_id),
    )


async def get_leaderboard(db: Database, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
    rows = await db.fetchall(
        "select user_id, balance from economy_balances where guild_id = ?"
        " order by balance desc limit ?",
        (guild_id, limit),
    )
    return [(int(r[0]), int(r[1])) for r in rows]

