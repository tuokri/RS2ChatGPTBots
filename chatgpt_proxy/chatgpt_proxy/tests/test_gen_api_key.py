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
import hashlib
import ipaddress
from typing import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio

from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries
from chatgpt_proxy.gen_api_key import async_main
from chatgpt_proxy.tests import setup

setup.common_test_setup()

_db_timeout = 30.0


@pytest_asyncio.fixture
async def gen_api_key_fixture() -> AsyncGenerator[asyncpg.Connection]:
    db_fixture_pool = await asyncpg.create_pool(
        dsn=setup.db_base_url,
        min_size=1,
        max_size=1,
        timeout=_db_timeout,
    )

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await setup.drop_test_db(conn, timeout=_db_timeout)
        await setup.create_test_db(conn, timeout=_db_timeout)

    test_db_pool = await asyncpg.create_pool(
        dsn=setup.db_test_url,
        min_size=1,
        max_size=1,
        timeout=_db_timeout,
    )

    async with pool_acquire(
            test_db_pool,
            timeout=_db_timeout,
    ) as conn:
        async with conn.transaction():
            await setup.initialize_test_db(conn, timeout=_db_timeout)

        yield conn

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await setup.drop_test_db(conn, timeout=_db_timeout)

    await db_fixture_pool.close()
    await test_db_pool.close()


@pytest.mark.asyncio
async def test_gen_api_key_async_main(gen_api_key_fixture):
    conn = gen_api_key_fixture

    token = await async_main(
        game_server_address=ipaddress.IPv4Address("69.69.69.1"),
        game_server_port=69696,
        secret=setup.test_sanic_secret,
        issuer="test123",
        audience="test123",
        expires_at=datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=1),
        name="test_key_blabla",
    )

    assert token

    key = await queries.select_game_server_api_key(
        conn=conn,
        game_server_address=ipaddress.IPv4Address("69.69.69.1"),
        game_server_port=69696,
    )
    assert key

    assert key["api_key_hash"] == hashlib.sha256(token.encode()).digest()
