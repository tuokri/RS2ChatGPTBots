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
import logging
import threading
from typing import AsyncGenerator

import asyncpg
import nest_asyncio
import pytest
import pytest_asyncio
from pytest_loguru.plugin import caplog  # noqa: F401

from chatgpt_proxy.tests import setup  # noqa: E402

setup.common_test_setup()

import chatgpt_proxy.app  # noqa: E402
from chatgpt_proxy.app import db_maintenance  # noqa: E402
from chatgpt_proxy.db import pool_acquire  # noqa: E402
from chatgpt_proxy.log import logger  # noqa: E402

logger.level("DEBUG")

_db_timeout = setup.default_test_db_timeout

_background_tasks = set()


@pytest_asyncio.fixture
async def maintenance_fixture(
) -> AsyncGenerator[asyncpg.Connection]:
    loop = asyncio.get_running_loop()
    nest_asyncio.apply(loop=loop)

    db_fixture_pool = await asyncpg.create_pool(
        dsn=setup.db_base_url,
        min_size=1,
        max_size=1,
        timeout=_db_timeout,
        loop=loop,
    )

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await setup.drop_test_db(conn, timeout=_db_timeout)
        await setup.create_test_db(conn, timeout=_db_timeout)

    test_db_pool = await asyncpg.create_pool(
        dsn=setup.db_test_url,
        min_size=1,
        max_size=1,
        timeout=_db_timeout,
        loop=loop,
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


async def delayed_stop_task(delay: float, stop_event: threading.Event):
    logger.info("setting stop_event after: {} seconds", delay)
    await asyncio.sleep(delay)
    stop_event.set()
    logger.info("stop_event set")


def schedule_delayed_stop(delay: float, stop_event: threading.Event):
    if stop_event.is_set():
        logger.info("stop_event already set, not scheduling stop task")
        return

    task = asyncio.create_task(delayed_stop_task(delay, stop_event))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# TODO: to speed up completion of these tests, actively poll for the
#       desired result (or timeout), and set the stop_event when desired
#       result is reached.


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_db_maintenance(maintenance_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _ = maintenance_fixture

    chatgpt_proxy.app.db_maintenance_interval = 0.5

    # TODO: fill database with completed games and
    #       old API keys.

    stop_event = threading.Event()
    schedule_delayed_stop(1.0, stop_event)
    await db_maintenance(stop_event)


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_refresh_steam_web_api_cache(maintenance_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _ = maintenance_fixture

    # TODO: fill database with API keys and ???.

    chatgpt_proxy.app.steam_web_api_cache_refresh_interval = 0.5

    stop_event = threading.Event()
    schedule_delayed_stop(1.0, stop_event)
    # TODO: this needs mocked Steam Web API (see test_api.py).
    # await refresh_steam_web_api_cache(stop_event)
