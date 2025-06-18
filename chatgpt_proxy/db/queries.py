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


async def insert_game(
        conn: Connection,
        game_id: str,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        start_time: datetime.datetime,
        stop_time: datetime.datetime | None = None,
):
    await conn.execute(
        """
        INSERT INTO "game" (id, start_time, stop_time, game_server_address, game_server_port)
        VALUES ($1, $2, $3, $4, $5)
        """,
        game_id,
        start_time,
        stop_time,
        game_server_address,
        game_server_port,
    )


async def delete_completed_games(
        conn: Connection,
        game_expiration: datetime.timedelta,
) -> str:
    return await conn.execute(
        """
        DELETE
        FROM "game"
        WHERE stop_time IS NOT NULL
           OR NOW() > (stop_time + $1)
        """,
        game_expiration,
    )
