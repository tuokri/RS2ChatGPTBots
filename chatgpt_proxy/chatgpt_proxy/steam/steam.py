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

import asyncio

import asyncpg
import httpx
# noinspection PyProtectedMember
from httpx._types import QueryParamTypes

from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db.queries import increment_steam_web_api_queries

server_list_url = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"

_background_tasks = set()


async def _update_steam_web_api_queries_counter(
        pg_pool: asyncpg.Pool,
) -> None:
    async with pool_acquire(pg_pool) as conn:
        await increment_steam_web_api_queries(conn)


async def web_api_request(
        http_client: httpx.AsyncClient,
        pg_pool: asyncpg.Pool,
        url: str,
        params: QueryParamTypes | None = None,
) -> httpx.Response:
    update_counter_task = asyncio.create_task(
        _update_steam_web_api_queries_counter(pg_pool)
    )
    _background_tasks.add(update_counter_task)
    update_counter_task.add_done_callback(_background_tasks.discard)

    resp = await http_client.get(
        url,
        params=params,
    )
    return resp
