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
from pypika import Query
from pypika import Table

_default_conn_timeout = 15.0


class Ignored:
    pass


IGNORED = Ignored()


# TODO: add caching layer!

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


def build_update_game_query(
        game_id: str,
        stop_time: datetime.datetime | Ignored = IGNORED,
        openai_previous_response_id: str | Ignored = IGNORED,
) -> Query:
    game = Table(name="game")
    query = Query.update(game)
    if stop_time is not IGNORED:
        query = query.set(game.stop_time, stop_time)
    if openai_previous_response_id is not IGNORED:
        query = query.set(game.openai_previous_response_id, openai_previous_response_id)
    query = query.where(game.id == game_id)
    return query


async def update_game(
        conn: Connection,
        game_id: str,
        stop_time: datetime.datetime | Ignored = IGNORED,
        openai_previous_response_id: str | Ignored = IGNORED,
        timeout: float | None = _default_conn_timeout,
):
    query = build_update_game_query(
        game_id=game_id,
        stop_time=stop_time,
        openai_previous_response_id=openai_previous_response_id,
    )
    await conn.execute(str(query), timeout=timeout)


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
        SELECT *
        FROM "game"
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
            SET game_id    = excluded.game_id,
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


# TODO: add the rest of cols here if needed?
async def select_game_server_api_key(
        conn: Connection,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        timeout: float | None = _default_conn_timeout,
) -> Record | None:
    return await conn.fetchrow(
        """
        SELECT *
        FROM "game_server_api_key"
        WHERE game_server_address = $1
          AND game_server_port = $2;
        """,
        game_server_address,
        game_server_port,
        timeout=timeout,
    )


async def game_exists(
        conn: Connection,
        game_id: str,
        timeout: float | None = _default_conn_timeout,
) -> bool:
    return await conn.fetchval(
        """
        SELECT 1
        FROM "game"
        WHERE id = $1;
        """,
        game_id,
        timeout=timeout,
    ) is not None


async def delete_old_api_keys(
        conn: Connection,
        leeway: datetime.timedelta,
        timeout: float | None = _default_conn_timeout,
) -> str:
    return await conn.execute(
        """
        DELETE
        FROM "game_server_api_key"
        WHERE NOW() > (expires_at + $1);
        """,
        leeway,
        timeout=timeout,
    )


async def insert_openai_query(
        conn: Connection,
        time: datetime.datetime,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        request_length: int,
        response_length: int | None = None,
        timeout: float | None = _default_conn_timeout,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO "openai_query"
        (time, game_server_address, game_server_port, request_length, response_length)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id;
        """,
        time,
        game_server_address,
        game_server_port,
        request_length,
        response_length,
        timeout=timeout,
    )


async def update_openai_query(
        conn: Connection,
        query_id: int,
        response_length: int | None = None,
        timeout: float | None = _default_conn_timeout,
):
    """Assuming we ever need to update only response_length!"""
    await conn.execute(
        """
        UPDATE "openai_query"
        SET response_length = $2
        WHERE id = $1;
        """,
        query_id,
        response_length,
        timeout=timeout,
    )
