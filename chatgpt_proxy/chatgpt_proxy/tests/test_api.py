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
import ipaddress
import logging
import os
from typing import AsyncGenerator

import asyncpg
import httpx
import jwt
import nest_asyncio
import openai.types.responses as openai_responses
import pytest
import pytest_asyncio
import respx
from pytest_loguru.plugin import caplog  # noqa: F401
from sanic.log import access_logger as sanic_access_logger
from sanic.log import logger as sanic_logger
from sanic_testing.reusable import ReusableClient

from chatgpt_proxy.tests import setup  # noqa: E402

setup.common_test_setup()

# noinspection PyUnresolvedReferences
import chatgpt_proxy  # noqa: E402
from chatgpt_proxy import auth  # noqa: E402
from chatgpt_proxy.app import api_v1  # noqa: E402
from chatgpt_proxy.app import app  # noqa: E402
from chatgpt_proxy.app import game_id_length  # noqa: E402
from chatgpt_proxy.app import make_app  # noqa: E402
from chatgpt_proxy.app import max_ast_literal_eval_size  # noqa: E402
from chatgpt_proxy.cache import app_cache  # noqa: E402
from chatgpt_proxy.db import models  # noqa: E402
from chatgpt_proxy.db import pool_acquire  # noqa: E402
from chatgpt_proxy.db import queries  # noqa: E402
from chatgpt_proxy.db.models import SayType  # noqa: E402
from chatgpt_proxy.db.models import Team  # noqa: E402
from chatgpt_proxy.log import logger  # noqa: E402
from chatgpt_proxy.tests.client import SpoofedSanicASGITestClient  # noqa: E402
from chatgpt_proxy.tests.monkey_patch import monkey_patch_sanic_testing  # noqa: E402
from chatgpt_proxy.types import App  # noqa: E402
from chatgpt_proxy.utils import utcnow  # noqa: E402

logger.level("DEBUG")

_asgi_host = "127.0.0.1"

monkey_patch_sanic_testing(
    asgi_host=_asgi_host,
)

_db_timeout = 30.0

_game_server_address = ipaddress.IPv4Address("127.0.0.1")
_game_server_port = 7777
_now = utcnow()
_iat = _now
_exp = _now + datetime.timedelta(hours=12)
_token = jwt.encode(
    key=setup.test_sanic_secret,
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

_token_bad_extra_metadata = jwt.encode(
    key=setup.test_sanic_secret,
    algorithm="HS256",
    payload={
        "iss": auth.jwt_issuer,
        "aud": auth.jwt_audience,
        "sub": f"{_game_server_address}:{_game_server_port}",
        "iat": int(_iat.timestamp()),
        "exp": int(_exp.timestamp()),
        "whatthefuck": "hmm?",
    },
)

_forbidden_game_server_address = ipaddress.IPv4Address("88.99.12.1")
_forbidden_game_server_port = 6969
_token_for_forbidden_server = jwt.encode(
    key=setup.test_sanic_secret,
    algorithm="HS256",
    payload={
        "iss": auth.jwt_issuer,
        "aud": auth.jwt_audience,
        "sub": f"{_forbidden_game_server_address}:{_forbidden_game_server_port}",
        "iat": int(_iat.timestamp()),
        "exp": int(_exp.timestamp()),
    },
)
_token_for_forbidden_server_sha256 = hashlib.sha256(
    _token_for_forbidden_server.encode()).digest()

_steam_web_api_get_server_list_dummy_filter = (
    f"\\gamedir\\rs2\\gameaddr\\{_game_server_address}:{_game_server_port}")

app.config.ACCESS_LOG = True
app.config.OAS = False
app.config.OAS_AUTODOC = False
sanic_logger.setLevel(logging.DEBUG)
sanic_access_logger.setLevel(logging.DEBUG)

# TODO: maybe just use namedtuple?
ApiFixtureTuple = tuple[
    App,
    ReusableClient,
    respx.MockRouter,
    respx.MockRouter,
    asyncpg.Connection,
]


@pytest_asyncio.fixture
async def api_fixture(
) -> AsyncGenerator[ApiFixtureTuple]:
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

    response = openai_responses.Response(
        id="testing_0",
        model="gpt-4.1",
        created_at=utcnow().timestamp(),
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

            await queries.insert_game_server_api_key(
                conn=conn,
                issued_at=_iat,
                expires_at=_exp,
                token_hash=_token_sha256,
                game_server_address=_game_server_address,
                game_server_port=_game_server_port,
                name="pytest API key",
            )
            await queries.insert_game_server_api_key(
                conn=conn,
                issued_at=_iat,
                expires_at=_exp,
                token_hash=_token_for_forbidden_server_sha256,
                game_server_address=_forbidden_game_server_address,
                game_server_port=_forbidden_game_server_port,
                name="pytest API key (forbidden game server)",
            )

        app.asgi_client.headers = _headers
        app.asgi_client.loop = loop

        with (respx.MockRouter(
                base_url="https://api.openai.com/",
                assert_all_called=False,
        ) as openai_mock_router,
            respx.MockRouter(
                base_url="https://api.steampowered.com",
                assert_all_called=False,
            ) as steam_web_api_mock_router
        ):
            openai_mock_router.route(host=_asgi_host).pass_through()
            openai_mock_router.post("/v1/responses").mock(
                return_value=httpx.Response(
                    status_code=200,
                    json=response.model_dump(mode="json"),
                ))

            steam_web_api_mock_router.route(host=_asgi_host).pass_through()
            steam_web_api_mock_router.get(
                "IGameServersService/GetServerList/v1/",
                params={
                    "key": setup.steam_web_api_key,
                    "filter": _steam_web_api_get_server_list_dummy_filter,
                }
            ).mock(
                return_value=httpx.Response(
                    status_code=200,
                    json={
                        "response": {
                            "servers": [
                                {
                                    "addr": "127.0.0.1:27015",
                                    "gameport": 7777,
                                    "steamid": "43215698745632158",
                                    "name": "Dummy Server for pytest",
                                    "appid": 418460,
                                    "gamedir": "RS2",
                                    "version": "1094",
                                    "product": "RS2",
                                    "region": 255,
                                    "players": 3,
                                    "max_players": 64,
                                    "bots": 0,
                                    "map": "VNSK-Riverbed",
                                    "secure": True,
                                    "dedicated": True,
                                    "os": "w",
                                    "gametype": "does_not_matter"
                                },
                            ],
                        },
                    },
                ))

            # NOTE: can't reuse the same app for ReusableClient!
            reusable_app = make_app("ChatGPTProxy-Reusable")
            reusable_app.blueprint(api_v1)
            reusable_client = ReusableClient(
                reusable_app,
                host=_asgi_host,
                loop=loop,
                client_kwargs={
                    "headers": _headers,
                }
            )

            with reusable_client:
                yield app, reusable_client, openai_mock_router, steam_web_api_mock_router, conn

    async with pool_acquire(db_fixture_pool, timeout=_db_timeout) as conn:
        await setup.drop_test_db(conn, timeout=_db_timeout)

    await db_fixture_pool.close()
    await test_db_pool.close()


@pytest.mark.asyncio
async def test_api_v1_post_game(api_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    api_app, reusable_client, openai_mock_router, steam_mock_router, db_conn = api_fixture

    data = "VNTE-TestSuite\n7777"
    req, resp = reusable_client.post("/api/v1/game", data=data)
    assert resp.status == 201

    game_id, greeting = resp.text.split("\n")
    assert len(game_id) == game_id_length * 2  # Num bytes as hex string.

    req, resp = reusable_client.get(f"/api/v1/game/{game_id}")
    assert resp.status == 200
    game = resp.json
    assert game


@pytest.mark.asyncio
async def test_api_v1_post_game_invalid_token(api_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    api_app, reusable_client, openai_mock_router, steam_mock_router, db_conn = api_fixture

    # No token.
    logger.info("testing no token")
    data = "VNTE-TestSuite\n7777"
    req, resp = reusable_client.post(
        "/api/v1/game",
        data=data,
        headers={
            "Authorization": "",
        },
    )
    assert resp.status == 401

    # Bad token (garbage data).
    logger.info("testing bad token")
    data = "VNTE-TestSuite\n7777"
    req, resp = reusable_client.post(
        "/api/v1/game",
        data=data,
        headers={
            "Authorization": "Bearer aasddsadasasdadsadsdsaasdasdads",
        },
    )
    assert resp.status == 401

    # Good token with unwanted extra claims added
    # -> token hash check mismatch with database-stored hash.
    logger.info("testing token with extra metadata")
    data = "VNTE-TestSuite\n7777"
    req, resp = reusable_client.post(
        "/api/v1/game",
        data=data,
        headers={
            "Authorization": f"Bearer {_token_bad_extra_metadata}",
        },
    )
    assert resp.status == 401

    logger.info("testing Steam not recognizing the dedicated server")
    with steam_mock_router:
        steam_mock_router.get(
            "IGameServersService/GetServerList/v1/",
            params={
                "key": setup.steam_web_api_key,
                "filter": _steam_web_api_get_server_list_dummy_filter,
            }
        ).mock(
            return_value=httpx.Response(
                status_code=200,
                json={
                    "response": {
                        "servers": [],
                    },
                },
            ))
        data = "VNTE-WhatTheFuckBro\n7777"
        req, resp = reusable_client.post("/api/v1/game", data=data)
        assert resp.status == 401

    logger.info("testing Steam API returning garbage")
    with steam_mock_router:
        steam_mock_router.get(
            "IGameServersService/GetServerList/v1/",
            params={
                "key": setup.steam_web_api_key,
                "filter": _steam_web_api_get_server_list_dummy_filter,
            }
        ).mock(
            return_value=httpx.Response(
                status_code=200,
                json={
                    "blasdalsd": {
                        "xorvors": [],
                    },
                },
            ))
        data = "VNTE-WhatTheFuckBro\n7777"
        req, resp = reusable_client.post("/api/v1/game", data=data)
        assert resp.status == 401

    logger.info("testing token meant for another IP address (but the token exists in the DB)")
    data = "VNTE-ThisDoesntMatterLol\n7777"
    req, resp = reusable_client.post(
        "/api/v1/game",
        data=data,
        headers={
            "Authorization": f"Bearer {_token_for_forbidden_server}",
        },
    )
    assert resp.status == 401

    logger.info("testing token meant for another IP address")
    spoofed_asgi_client = SpoofedSanicASGITestClient(
        app=api_app,
        client_ip="6.0.28.175",
    )
    somebody_elses_token = jwt.encode(
        key=setup.test_sanic_secret,
        algorithm="HS256",
        payload={
            "iss": auth.jwt_issuer,
            "aud": auth.jwt_audience,
            "sub": "6.0.28.175:55555",  # Also, this does not exist in the DB.
            "iat": int(_iat.timestamp()),
            "exp": int(_exp.timestamp()),
        },
    )
    spoofed_asgi_client.headers = {
        "Authorization": f"Bearer {somebody_elses_token}",
    }
    data = "VNTE-TestSuite\n55555"
    # noinspection PyTypeChecker
    req, resp = await spoofed_asgi_client.post("/api/v1/game", data=data)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_api_v1_post_game_chat_message(api_fixture, caplog) -> None:
    # TODO: maybe just parametrize this test.

    caplog.set_level(logging.DEBUG)
    api_app, reusable_client, openai_mock_router, steam_mock_router, db_conn = api_fixture

    path = "/api/v1/game/first_game/chat_message"
    data = models.GameChatMessage(
        id=0,
        sender_name="my name is dog69",
        sender_team=Team.North,
        channel=SayType.ALL,
        message="this is the actual message!",
        game_id="first_game",
        send_time=utcnow(),
    ).wire_format()
    req, resp = reusable_client.post(path, data=data)
    assert resp.status == 204

    path_404 = "/api/v1/game/THIS_GAME_DOES_NOT_EXIST/chat_message"
    data = "my name is dog69\n0\n0\nthis is the actual message!"
    req, resp = reusable_client.post(path_404, data=data)
    assert resp.status == 404

    path_forbidden = "/api/v1/game/game_from_forbidden_server/chat_message"
    data = "my name is dog69\n0\n0\nthis is the actual message!"
    req, resp = reusable_client.post(path_forbidden, data=data)
    assert resp.status == 401

    path = "/api/v1/game/first_game/chat_message"
    invalid_data = "dsfsdsfdsffdsfsdsdf"
    req, resp = reusable_client.post(path, data=invalid_data)
    assert resp.status == 400

    path = "/api/v1/game/first_game/chat_message"
    empty_data = ""
    req, resp = reusable_client.post(path, data=empty_data)
    assert resp.status == 400

    path = "/api/v1/game/first_game/chat_message"
    req, resp = reusable_client.post(path)  # No data.
    assert resp.status == 400

    # Steam Web API key is not set -> the result should still be the same,
    # only with a warning logged, but don't bother asserting the log message.
    # Run this check for coverage.
    try:
        # Make sure there aren't any cached Steam Web API results.
        await app_cache.clear()
        del os.environ["STEAM_WEB_API_KEY"]
        chatgpt_proxy.auth.load_config()
        path = "/api/v1/game/first_game/chat_message"
        data = "my name is dog69\n0\n0\nthis is the actual message!"
        req, resp = reusable_client.post(path, data=data)
        assert resp.status == 204
    finally:
        os.environ["STEAM_WEB_API_KEY"] = setup.steam_web_api_key
        chatgpt_proxy.auth.load_config()


@pytest.mark.asyncio
async def test_database_maintenance(api_fixture, caplog) -> None:
    # TODO: how to test this in a robust manner?
    pass


@pytest.mark.asyncio
async def test_api_v1_put_delete_game_player(api_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    api_app, reusable_client, openai_mock_router, steam_mock_router, db_conn = api_fixture

    # PUT a new player -> should be 201 CREATED.
    new_player_id = 69696
    path = f"/api/v1/game/first_game/player/{new_player_id}"
    data = "Bob\n1\n-50"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 201
    player = await queries.select_game_player(
        conn=db_conn,
        game_id="first_game",
        player_id=new_player_id,
    )
    assert player == models.GamePlayer(
        game_id="first_game",
        id=new_player_id,
        name="Bob",
        team=Team.South,
        score=-50,
    )

    # PUT existing player -> should be 204 NO CONTENT.
    data = models.GamePlayer(
        game_id="first_game",
        id=new_player_id,
        name="Bob",
        team=Team.South,
        score=6969,
    ).wire_format()
    path = f"/api/v1/game/first_game/player/{new_player_id}"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 204
    player = await queries.select_game_player(
        conn=db_conn,
        game_id="first_game",
        player_id=new_player_id,
    )
    assert player == models.GamePlayer(
        game_id="first_game",
        id=new_player_id,
        name="Bob",
        team=Team.South,
        score=6969,
    )

    # Delete existing -> NO CONTENT.
    path = f"/api/v1/game/first_game/player/{new_player_id}"
    req, resp = reusable_client.delete(path)
    assert resp.status == 204

    # Second delete, should already be gone -> 404.
    path = f"/api/v1/game/first_game/player/{new_player_id}"
    req, resp = reusable_client.delete(path)
    assert resp.status == 404

    # Delete player that never existed -> 404.
    path = "/api/v1/game/first_game/player/6904234"
    req, resp = reusable_client.delete(path)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_api_v1_put_game_objective_state(api_fixture, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    api_app, reusable_client, openai_mock_router, steam_mock_router, db_conn = api_fixture

    # Empty data -> 400.
    data = ""
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Empty list (first request) -> clears state -> 201.
    data = "[]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 201

    # Empty list (subsequent request) -> clears state -> 204.
    data = "[]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 204

    # Valid list (subsequent request) -> 204.
    neutral_team = int(Team.Neutral)
    data = f"[('BlaBla',0),('SomeObjective',1),('Neutral Objective',{neutral_team})]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 204

    # Valid list (subsequent request) -> 2024.
    data = models.GameObjectiveState(
        game_id="first_game",
        objectives=[
            models.GameObjective(
                name="BlaBla",
                team_state=models.Team.North,
            ),
            models.GameObjective(
                name="AnotherObjective",
                team_state=models.Team.South,
            ),
            models.GameObjective(
                name="THIS IS SOME WEIRD OBJECTIVE 123123",
                team_state=models.Team.Neutral,
            ),
        ]
    ).wire_format()
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 204

    # Bad data -> 400.
    data = "asdasd."
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Bad data -> 400.
    data = "[(),()]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Bad data -> 400.
    data = "["
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Bad data -> 400.
    data = "[)"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Too much data -> 400.
    data = "*" * (max_ast_literal_eval_size + 1)
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Valid but wrong Python object.
    data = "()"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Valid but wrong Python object.
    data = "[(1,1)]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Valid but wrong Python object.
    data = "[('ValidString','this_should_be_an_int')]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400

    # Valid but wrong Python object.
    invalid_team_as_int = 696969
    data = f"[('ValidString',{invalid_team_as_int})]"
    path = "/api/v1/game/first_game/objective_state"
    req, resp = reusable_client.put(path, data=data)
    assert resp.status == 400
