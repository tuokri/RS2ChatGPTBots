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

"""Database connection and caching utilities."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from typing import cast

from asyncpg import Connection
from asyncpg import Pool

from chatgpt_proxy.log import logger

_default_acquire_timeout = 5.0


@asynccontextmanager
async def pool_acquire(
        pool: Pool,
        timeout: float = _default_acquire_timeout,
) -> AsyncGenerator[Connection]:
    conn: Connection
    async with pool.acquire(timeout=timeout) as conn:
        yield conn


@asynccontextmanager
async def pool_acquire_many(
        pool: Pool,
        count: int,
        timeout: float = _default_acquire_timeout,
) -> AsyncGenerator[list[Connection]]:
    conns: list[Connection] = []
    try:
        for _ in range(count):
            # noinspection PyUnresolvedReferences
            conn = cast(Connection, await pool.acquire(timeout=timeout))
            conns.append(conn)
        yield conns
    finally:
        for conn in conns:
            try:
                await conn.close(timeout=timeout)
            except Exception as e:
                logger.debug(
                    "error closing connection: {}: {}",
                    type(e).__name__, e)
