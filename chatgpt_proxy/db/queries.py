# MIT License
#
# Copyright (c) 2025 Tuomo Kriikkula
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import datetime
import ipaddress

from asyncpg import Connection
from asyncpg import Record

_default_conn_timeout = 15.0


async def insert_game(
        conn: Connection,
        game_id: str,
        level: str,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        start_time: datetime.datetime,
        stop_time: datetime.datetime | None = None,
        timeout: float | None = _default_conn_timeout,
):
    await conn.execute(
        """
        INSERT INTO "game"
        (id, level, start_time, stop_time, game_server_address, game_server_port)
        VALUES ($1, $2, $3, $4, $5, $6);
        """,
        game_id,
        level,
        start_time,
        stop_time,
        game_server_address,
        game_server_port,
        timeout=timeout,
    )


# NOTE: assuming we only ever have to update stop_time!
async def update_game(
        conn: Connection,
        game_id: str,
        stop_time: datetime.datetime,
        timeout: float | None = _default_conn_timeout,
):
    raise NotImplementedError


# TODO: what's the best way to handle this? If we make this too dynamic
#       it's going to cross into ORM territory quickly.
#       For now, assume we only ever want to select by game_id and
#       return all columns even if it is wasteful.
async def select_game(
        conn: Connection,
        game_id: str,
        timeout: float | None = _default_conn_timeout,
) -> Record | None:
    return await conn.fetchrow(
        """
        SELECT * FROM "game"
        WHERE id = $1;
        """,
        game_id,
        timeout=timeout,
    )


async def upsert_game_objective_state(
        conn: Connection,
        game_id: str,
        objectives: list[list[str]],
        timeout: float | None = _default_conn_timeout,
):
    await conn.execute(
        """
        INSERT INTO "game_objective_state" (game_id, objectives)
        VALUES ($1, $2)
        ON CONFLICT DO UPDATE
        SET game_id = excluded.game_id,
            objectives = excluded.objectives;
        """,
        game_id,
        objectives,
        timeout=timeout,
    )


async def delete_completed_games(
        conn: Connection,
        game_expiration: datetime.timedelta,
        timeout: float | None = _default_conn_timeout,
) -> str:
    return await conn.execute(
        """
        DELETE
        FROM "game"
        WHERE stop_time IS NOT NULL
           OR NOW() > (stop_time + $1);
        """,
        game_expiration,
        timeout=timeout,
    )
