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

"""Database query helpers."""

import datetime
import ipaddress

from asyncpg import Connection
from asyncpg import Record
from pypika import Order
from pypika import Query
from pypika import Table

from chatgpt_proxy.db import models

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
        openai_previous_response_id: str | None = None,
        timeout: float | None = _default_conn_timeout,
):
    await conn.execute(
        """
        INSERT INTO "game"
        (id, level, start_time, stop_time, game_server_address,
         game_server_port, openai_previous_response_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7);
        """,
        game_id,
        level,
        start_time,
        stop_time,
        game_server_address,
        game_server_port,
        openai_previous_response_id,
        timeout=timeout,
    )


def build_update_game_query(
        game_id: str,
        stop_time: datetime.datetime | Ignored = IGNORED,
        openai_previous_response_id: str | Ignored = IGNORED,
) -> Query:
    game = Table(name="game")
    query = game.update()
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
) -> models.Game | None:
    record = await conn.fetchrow(
        """
        SELECT *
        FROM "game"
        WHERE id = $1;
        """,
        game_id,
        timeout=timeout,
    )

    if record:
        return models.Game(**record)

    return None


# TODO: select * or do we need a way to specify columns?
async def select_games(
        conn: Connection,
        timeout: float | None = _default_conn_timeout,
) -> list[models.Game]:
    games = await conn.fetch(
        """
        SELECT *
        FROM "game";
        """,
        timeout=timeout,
    )
    return [
        models.Game(**game)
        for game in games if game
    ]


async def upsert_game_objective_state(
        conn: Connection,
        state: models.GameObjectiveState,
        timeout: float | None = _default_conn_timeout,
) -> bool:
    # TODO: re-consider what's the best data format for this in DB?
    objectives_db_fmt = [obj.wire_format() for obj in state.objectives]

    inserted = await conn.fetchval(
        """
        INSERT INTO "game_objective_state" (game_id, objectives)
        VALUES ($1, $2)
        ON CONFLICT (game_id) DO UPDATE
            SET objectives = excluded.objectives
        RETURNING (xmax = 0) as inserted;
        """,
        state.game_id,
        objectives_db_fmt,
        timeout=timeout,
    )
    return bool(inserted)


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


async def select_game_server_api_keys(
        conn: Connection,
        timeout: float | None = _default_conn_timeout,
) -> list[Record]:
    return await conn.fetch(
        """
        SELECT *
        FROM "game_server_api_key";
        """,
        timeout=timeout,
    )


async def insert_game_server_api_key(
        conn: Connection,
        issued_at: datetime.datetime,
        expires_at: datetime.datetime,
        token_hash: bytes,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        name: str | None = None,
        timeout: float | None = _default_conn_timeout,
):
    await conn.execute(
        """
        INSERT INTO "game_server_api_key"
        (created_at, expires_at, api_key_hash, game_server_address, game_server_port, name)
        VALUES ($1, $2, $3, $4, $5, $6);
        """,
        issued_at,
        expires_at,
        token_hash,
        game_server_address,
        game_server_port,
        name,
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


async def select_openai_query(
        conn: Connection,
        openai_response_id: str,
        timeout: float | None = _default_conn_timeout,
) -> models.OpenAIQuery | None:
    """NOTE: for now, assuming we only want to select by openai_response_id."""
    record = await conn.fetchrow(
        """
        SELECT *
        FROM "openai_query"
        WHERE openai_response_id = $1;
        """,
        openai_response_id,
        timeout=timeout,
    )

    if not record:
        return None

    return models.OpenAIQuery(**record)


async def insert_openai_query(
        conn: Connection,
        game_id: str,
        time: datetime.datetime,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        request_length: int,
        response_length: int,
        openai_response_id: str,
        timeout: float | None = _default_conn_timeout,
) -> None:
    await conn.execute(
        """
        INSERT INTO "openai_query"
        (game_id, time, game_server_address,
         game_server_port, request_length, response_length, openai_response_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7);
        """,
        game_id,
        time,
        game_server_address,
        game_server_port,
        request_length,
        response_length,
        openai_response_id,
        timeout=timeout,
    )


async def insert_game_chat_message(
        conn: Connection,
        game_id: str,
        message: str,
        send_time: datetime.datetime,
        sender_name: str,
        sender_team: models.Team,
        channel: models.SayType,
        timeout: float | None = _default_conn_timeout,
) -> int:
    _sender_team = int(sender_team)
    _channel = int(channel)

    return await conn.fetchval(
        """
        INSERT INTO "game_chat_message"
            (message, game_id, send_time, sender_name, sender_team, channel)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id;
        """,
        message,
        game_id,
        send_time,
        sender_name,
        _sender_team,
        _channel,
        timeout=timeout,
    )


async def insert_game_kill(
        conn: Connection,
        game_id: str,
        kill_time: datetime.datetime,
        killer_name: str,
        victim_name: str,
        killer_team: models.Team,
        victim_team: models.Team,
        damage_type: str,
        kill_distance_m: float,
        timeout: float | None = _default_conn_timeout,
) -> int:
    _killer_team = int(killer_team)
    _victim_team = int(victim_team)

    return await conn.fetchval(
        """
        INSERT INTO "game_kill"
        (game_id, kill_time, killer_name, victim_name, killer_team,
         victim_team, damage_type, kill_distance_m)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id;
        """,
        game_id,
        kill_time,
        killer_name,
        victim_name,
        _killer_team,
        _victim_team,
        damage_type,
        kill_distance_m,
        timeout=timeout,
    )


async def delete_game_player(
        conn: Connection,
        game_id: str,
        player_id: int,
        timeout: float | None = _default_conn_timeout,
):
    await conn.execute(
        """
        DELETE
        FROM "game_player"
        WHERE game_id = $1
          AND id = $2;
        """,
        game_id,
        player_id,
        timeout=timeout,
    )


async def upsert_game_player(
        conn: Connection,
        game_id: str,
        player_id: int,
        name: str,
        team_index: int,
        score: float,
        timeout: float | None = _default_conn_timeout,
) -> bool:
    inserted = await conn.fetchval(
        """
        INSERT INTO "game_player" (game_id, id, name, team, score)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (id) DO UPDATE
            SET game_id = excluded.game_id,
                name    = excluded.name,
                team    = excluded.team,
                score   = excluded.score
        RETURNING (xmax = 0) as inserted;
        """,
        game_id,
        player_id,
        name,
        team_index,
        score,
        timeout=timeout,
    )
    return bool(inserted)


async def select_game_player(
        conn: Connection,
        game_id: str,
        player_id: int,
        timeout: float | None = _default_conn_timeout,
) -> models.GamePlayer | None:
    record = await conn.fetchrow(
        """
        SELECT *
        FROM "game_player"
        WHERE game_id = $1
          AND id = $2;
        """,
        game_id,
        player_id,
        timeout=timeout,
    )

    if not record:
        return None

    return models.GamePlayer(
        game_id=record["game_id"],
        id=record["id"],
        name=record["name"],
        team=models.Team(str(record["team"])),
        score=record["score"],
    )


async def game_player_exists(
        conn: Connection,
        game_id: str,
        player_id: int,
        timeout: float | None = _default_conn_timeout,
) -> bool:
    return await conn.fetchval(
        """
        SELECT 1
        FROM "game_player"
        WHERE game_id = $1
          AND id = $2;
        """,
        game_id,
        player_id,
        timeout=timeout,
    ) is not None


async def select_game_kills(
        conn: Connection,
        game_id: str | None = None,
        kill_time_from: datetime.datetime | None = None,
        limit: int | None = None,
        timeout: float | None = _default_conn_timeout,
) -> list[models.GameKill]:
    game_kill = Table(name="game_kill")
    query = game_kill.select("*")
    if game_id is not None:
        query = query.where(game_kill.game_id == game_id)
    if kill_time_from is not None:
        query = query.where(game_kill.kill_time >= kill_time_from)
    if limit is not None:
        query = query.limit(limit)
    query = query.orderby("id", order=Order.asc)

    records = await conn.fetch(
        str(query),
        timeout=timeout,
    )

    return [
        models.GameKill(**record)
        for record in records
    ]


async def select_game_chat_messages(
        conn: Connection,
        game_id: str | None = None,
        send_time_from: datetime.datetime | None = None,
        limit: int | None = None,
        timeout: float | None = _default_conn_timeout,
) -> list[models.GameChatMessage]:
    game_chat_message = Table(name="game_chat_message")
    query = game_chat_message.select("*")
    if game_id is not None:
        query = query.where(game_chat_message.game_id == game_id)
    if send_time_from is not None:
        query = query.where(game_chat_message.send_time >= send_time_from)
    if limit is not None:
        query = query.limit(limit)
    query = query.orderby("id", order=Order.asc)

    records = await conn.fetch(
        str(query),
        timeout=timeout,
    )

    return [
        models.GameChatMessage(**record)
        for record in records
    ]


async def increment_steam_web_api_queries(
        conn: Connection,
        timeout: float | None = _default_conn_timeout,
) -> None:
    async with conn.transaction():
        await conn.execute(
            """
            UPDATE "query_statistics"
            SET steam_web_api_queries    = steam_web_api_queries + 1,
                last_steam_web_api_query = NOW();
            """,
            timeout=timeout,
        )


async def select_steam_web_api_queries(
        conn: Connection,
        timeout: float | None = _default_conn_timeout,
) -> int:
    record = await conn.fetchrow(
        """
        SELECT steam_web_api_queries
        FROM "query_statistics";
        """,
        timeout=timeout,
    )
    return record["steam_web_api_queries"]
