import datetime
import hashlib
import ipaddress
import os
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
import jwt
import pytest
import pytest_asyncio
import respx

import chatgpt_proxy
from chatgpt_proxy import auth
from chatgpt_proxy.app import app
from chatgpt_proxy.common import App
from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries

_db_url = "postgresql://postgres:postgres@localhost:5432/"
_db_test_url = "postgresql://postgres:postgres@localhost:5432/chatgpt_proxy_tests"
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

    mock_router = respx.MockRouter()

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
        yield app, mock_router, conn

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await conn.execute(
            "DROP DATABASE IF EXISTS chatgpt_proxy_tests WITH (FORCE)",
            timeout=_db_timeout,
        )


@pytest.mark.asyncio
async def test_api_TODO(api_fixture) -> None:
    api_app, mock_router, db_conn = api_fixture

    req, resp = await api_app.asgi_client.get("/")
    print(f"{req.headers=}")
    print(f"{resp.headers=}")
    assert resp.status == 404
