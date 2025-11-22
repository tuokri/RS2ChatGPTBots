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
import datetime
import hashlib
import logging
import random
import threading
from typing import AsyncGenerator
from typing import Callable
from typing import Coroutine

import asyncpg
import nest_asyncio
import pytest
import pytest_asyncio
from pytest_loguru.plugin import caplog  # noqa: F401

from chatgpt_proxy.db import queries
from chatgpt_proxy.tests import setup  # noqa: E402
from chatgpt_proxy.utils import utils

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
    global _task_exception
    _task_exception = None

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


async def delayed_check_task(
        stop_event: threading.Event,
        check_result_coro: Callable[[], Coroutine[None, None, bool]],
        timeout: float,
):
    try:
        now = datetime.datetime.now()
        to = now + datetime.timedelta(seconds=timeout)
        while not await check_result_coro():
            now = datetime.datetime.now()
            if now > to:
                # TODO: would be nice to communicate the reason here,
                #       for example by somehow returning a 'context'
                #       from check_result_coro!
                raise TimeoutError("timed out")
            await asyncio.sleep(0.05)
    finally:
        stop_event.set()


_task_exception: BaseException | None = None


def schedule_delayed_check(
        stop_event: threading.Event,
        check_result_coro: Callable[[], Coroutine[None, None, bool]],
        timeout: float,
):
    task = asyncio.create_task(
        delayed_check_task(stop_event, check_result_coro, timeout))
    _background_tasks.add(task)

    def check_task(task_: asyncio.Task[None]):
        global _task_exception
        ex = task_.exception()
        if ex:
            logger.error("task failed: {}: {}", task_, type(ex).__name__)
            _task_exception = ex

    task.add_done_callback(check_task)
    task.add_done_callback(_background_tasks.discard)


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_db_maintenance(maintenance_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    db_conn = maintenance_fixture

    chatgpt_proxy.app.db_maintenance_interval = 0.5

    old_game_ids = [
        "OLD_GAME_0",
        "OLD_GAME_1",
        "OLD_GAME_2",
    ]

    expr = chatgpt_proxy.app.game_expiration
    expr_hours = expr.total_seconds() // 3600

    await db_conn.execute(
        f"""
            INSERT INTO "game" (id,
                                level,
                                start_time,
                                stop_time,
                                game_server_address,
                                game_server_port,
                                openai_previous_response_id)
            VALUES ('{old_game_ids[0]}',
                    'VNTE-Mapperino',
                    NOW() - INTERVAL '{expr_hours + 10} hours',
                    NOW() - INTERVAL '{expr_hours + 9} hours',
                    INET '127.0.1.1',
                    7777,
                    'openai_dummy_id_1'),
                   ('{old_game_ids[1]}',
                    'RRTE-DogCat',
                    NOW() - INTERVAL '{expr_hours + 9} hours',
                    NOW() - INTERVAL '{expr_hours + 8} hours',
                    INET '127.0.1.1',
                    7777,
                    'openai_dummy_id_2'),
                   ('{old_game_ids[2]}',
                    'VNSU-AnLaoValleyXD',
                    NOW() - INTERVAL '{expr_hours + 2} hours',
                    NOW() - INTERVAL '{expr_hours + 1} hours',
                    INET '127.0.1.1',
                    7777,
                    'openai_dummy_id_2')
            ;
            """,
        timeout=_db_timeout,
    )

    now = utils.utcnow()
    creations = [
        now - datetime.timedelta(hours=x * 2, minutes=random.randint(0, 59))
        for x in range(5)
    ]
    expirations = [
        now - datetime.timedelta(hours=x + 1)
        for x in range(5)
    ]
    key_hashes = [
        hashlib.sha256(random.randbytes(64)).digest()
        for _ in range(5)
    ]

    for x, (created_at, expires_at, key_hash) in enumerate(zip(creations, expirations, key_hashes)):
        await db_conn.execute(
            f"""
            INSERT INTO "game_server_api_key"
            (created_at, expires_at, api_key_hash, game_server_address, game_server_port, name)
            VALUES
            ($1, $2, $3, INET '127.0.1.1', 7777, 'test_maintenance API key {x}');
            """,
            created_at,
            expires_at,
            key_hash,
            timeout=_db_timeout,
        )

    async def check_result() -> bool:
        games = await queries.select_games(db_conn)
        old_games_deleted = not any(
            game.id in old_game_ids
            for game in games
        )
        keys = await queries.select_game_server_api_keys(db_conn)
        old_api_keys_deleted = not any(
            key["api_key_hash"] in key_hashes
            for key in keys
        )
        return old_games_deleted and old_api_keys_deleted

    stop_event = threading.Event()
    schedule_delayed_check(stop_event, check_result_coro=check_result, timeout=5.0)
    await db_maintenance(stop_event)  # type: ignore[arg-type]
    if _task_exception:
        raise _task_exception


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_refresh_steam_web_api_cache(maintenance_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    db_conn = maintenance_fixture

    # TODO: fill database with API keys and ???.

    chatgpt_proxy.app.steam_web_api_cache_refresh_interval = 0.5

    async def check_result() -> bool:
        return True

    stop_event = threading.Event()
    schedule_delayed_check(stop_event, check_result_coro=check_result, timeout=5.0)
    # TODO: this needs mocked Steam Web API (see test_api.py).
    # await refresh_steam_web_api_cache(stop_event)
    if _task_exception:
        raise _task_exception
