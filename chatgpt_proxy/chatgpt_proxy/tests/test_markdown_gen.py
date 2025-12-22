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

from typing import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio

from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.tests import setup
from chatgpt_proxy.tests.setup import common_test_setup
from chatgpt_proxy.tests.setup import default_test_db_timeout
from chatgpt_proxy.utils import utcnow

common_test_setup()

from chatgpt_proxy.app import get_chat_messages_markdown_table  # noqa: E402
from chatgpt_proxy.app import get_kills_markdown_table  # noqa: E402
from chatgpt_proxy.app import get_scoreboard_markdown_table  # noqa: E402

_db_timeout = default_test_db_timeout


@pytest_asyncio.fixture
async def markdown_gen_fixture() -> AsyncGenerator[asyncpg.Connection]:
    pass


@pytest_asyncio.fixture
async def maintenance_fixture(
) -> AsyncGenerator[asyncpg.Connection]:
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
            await setup.seed_test_db(conn, timeout=_db_timeout)

        yield conn

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await setup.drop_test_db(conn, timeout=_db_timeout)

    await db_fixture_pool.close()
    await test_db_pool.close()


@pytest.mark.asyncio
async def test_markdown_gen(maintenance_fixture):
    conn = maintenance_fixture

    # TODO: fill DB with kills, players, etc.

    now_todo = utcnow()  # TODO
    _ = await get_scoreboard_markdown_table(conn, "TODO")
    _ = await get_kills_markdown_table(conn, "TODO", now_todo)
    _ = await get_chat_messages_markdown_table(conn, "TODO", now_todo)
