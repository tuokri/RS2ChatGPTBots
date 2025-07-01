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
import os
from pathlib import Path
from pprint import pprint
from typing import AsyncGenerator

import asyncpg
import httpx
import jwt
import openai.types.responses as openai_responses
import pytest
import pytest_asyncio
import respx

import chatgpt_proxy
from chatgpt_proxy import auth
from chatgpt_proxy.app import app
from chatgpt_proxy.app import game_id_length
from chatgpt_proxy.common import App
from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries
from chatgpt_proxy.tests.monkey_patch import monkey_patch_sanic_testing

monkey_patch_sanic_testing(
    asgi_host="127.0.0.1",
)

_db_url = "postgresql://postgres:postgres@localhost:5432"
_db_url = os.environ.get("DATABASE_URL", _db_url)
_db_test_url = f"{_db_url.rstrip("/")}/chatgpt_proxy_tests"
_db_timeout = 30.0

_root_path = Path(chatgpt_proxy.__file__).resolve().parent
_pkg_path_db = _root_path / "db/"
_pkg_path_tests = _root_path / "tests/"

assert _root_path.exists()
assert _pkg_path_db.exists()
assert _pkg_path_tests.exists()

_sanic_secret = "dummy"
_game_server_address = ipaddress.IPv4Address("127.0.0.1")
_game_server_port = 7777
_now = datetime.datetime.now(tz=datetime.timezone.utc)
_iat = _now
_exp = _now + datetime.timedelta(hours=12)
_token = jwt.encode(
    key=_sanic_secret,
    algorithm="HS256",
    payload={
        "iss": auth.jwt_issuer,
        "aud": auth.jwt_audience,
        "sub": f"{_game_server_address}:{_game_server_port}",
        "iat": int(_iat.timestamp()),
        "exp": int(_exp.timestamp()),
    },
)
_token_sha256 = hashlib.sha256(_token.encode()).digest()
_headers: dict[str, str] = {
    "Authorization": f"Bearer {_token}",
}


@pytest_asyncio.fixture
async def api_fixture(
) -> AsyncGenerator[tuple[App, respx.MockRouter, asyncpg.Connection]]:
    db_fixture_pool = await asyncpg.create_pool(
        dsn=_db_url,
        min_size=1,
        max_size=1,
        timeout=_db_timeout,
    )
    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await conn.execute(
            "DROP DATABASE IF EXISTS chatgpt_proxy_tests WITH (FORCE)",
            timeout=_db_timeout,
        )
        await conn.execute(
            "CREATE DATABASE chatgpt_proxy_tests",
            timeout=_db_timeout,
        )

    os.environ["SANIC_SECRET"] = _sanic_secret
    os.environ["OPENAI_API_KEY"] = "dummy"
    os.environ["DATABASE_URL"] = _db_test_url

    response = openai_responses.Response(
        id="testing_0",
        model="gpt-4.1",
        created_at=datetime.datetime.now(tz=datetime.timezone.utc).timestamp(),
        object="response",
        error=None,
        instructions=None,
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        output=[
            openai_responses.ResponseOutputMessage(
                id="msg_0_testing_0",
                content=[
                    openai_responses.ResponseOutputText(
                        annotations=[],
                        text="This is a mocked test message!",
                        type="output_text",
                    ),
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ],
    )

    test_db_pool = await asyncpg.create_pool(
        dsn=_db_test_url,
        min_size=1,
        max_size=1,
        timeout=_db_timeout,
    )

    init_db_sql = (_pkg_path_db / "db.sql").read_text()
    seed_db_sql = (_pkg_path_tests / "seed.sql").read_text()

    async with pool_acquire(
            test_db_pool,
            timeout=_db_timeout,
    ) as conn:
        async with conn.transaction():
            await conn.execute(init_db_sql, timeout=_db_timeout)
            await conn.execute(seed_db_sql, timeout=_db_timeout)
            await queries.insert_game_server_api_key(
                conn=conn,
                issued_at=_iat,
                expires_at=_exp,
                token_hash=_token_sha256,
                game_server_address=_game_server_address,
                game_server_port=_game_server_port,
                name="pytest API key",
            )

        app.asgi_client.headers = _headers
        with respx.mock(base_url="https://api.openai.com/", assert_all_called=False) as mock_router:
            mock_router.post("/v1/responses").mock(
                return_value=httpx.Response(
                    status_code=200,
                    json=response.model_dump(mode="json"),
                ))
            yield app, mock_router, conn

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await conn.execute(
            "DROP DATABASE IF EXISTS chatgpt_proxy_tests WITH (FORCE)",
            timeout=_db_timeout,
        )


@pytest.mark.asyncio
async def test_api_v1_post_game(api_fixture) -> None:
    api_app, mock_router, db_conn = api_fixture

    data = "VNTE-TestSuite\n7777"
    req, resp = await api_app.asgi_client.post("/api/v1/game", data=data)

    print(f"{req.headers=}")
    print(f"{resp.headers=}")

    assert resp.status == 201

    game_id, greeting = resp.text.split("\n")
    assert len(game_id) == game_id_length * 2  # Num bytes as hex string.

    req, resp = await api_app.asgi_client.get(f"/api/v1/game/{game_id}")
    assert resp.status == 200
    game = resp.json
    pprint(game)  # TODO: remove?
    assert game
