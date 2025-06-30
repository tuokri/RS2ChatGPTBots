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

# Implements a simple proxy server for communication between an UnrealScript
# client and OpenAI servers.

import ast
import asyncio
import datetime
import multiprocessing as mp
import os
import secrets
from enum import StrEnum
from http import HTTPStatus
from multiprocessing.synchronize import Event as EventType

import asyncpg
import openai
import sanic
from sanic import Blueprint
from sanic.response import HTTPResponse

from chatgpt_proxy.auth import auth
from chatgpt_proxy.common import App
from chatgpt_proxy.common import Context
from chatgpt_proxy.common import Request
from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries
from chatgpt_proxy.utils import get_remote_addr
from chatgpt_proxy.utils import is_prod_env

os.environ["LOGURU_AUTOINIT"] = "1"
from loguru import logger

api_v1 = Blueprint("api", version_prefix="/api/v", version=1)

app: App = sanic.Sanic("ChatGPTProxy", ctx=Context())
app.blueprint(api_v1)
# We don't expect UScript side to send large requests.
app.config.REQUEST_MAX_SIZE = 1500
app.config.REQUEST_MAX_HEADER_SIZE = 1500
# app.config.OAS = False
if is_prod_env:
    app.config.SECRET = os.environ["SANIC_SECRET"]
else:
    app.config.SECRET = os.environ.get("SANIC_SECRET", "TEST_SECRET_123123")
app.config.JWT_ISSUER = auth.jwt_issuer
app.config.JWT_AUDIENCE = auth.jwt_audience

# TODO: dynamic model selection?
openai_model = "gpt-4.1"

# Rough API design:
# - /message: to "fire" actual message request -> returns a chat message to send in game.
#    * all context data is taken into account
# - /message_history: (context) post here to keep a short log of previous chat messages.
# - /players: (context) post/delete here to keep the current player list up to date.
# - /kills: (context) post here to keep a short log of previous kills.
# - /base_prompt: (context) appended in front of all requests to the LLM.

# TODO: example prompt (the first one per game session).
# TODO: this should only be sent from the UScript side after a small
#       delay to allow the game state to "stabilize".
"""
{base_prompt}

This is the beginning of a new game. The game currently contains the following players.
```
Insert compact table of players (scoreboard).
```

The last {X} kills scored during the game are the following (in chronological order):
```
Insert compact table of kills here.
```

The last {X} chat messages sent during the game are the following (in chronological order):
```
Insert compact table of chat messages here.
```

{first_instruction}
"""
# TODO: subsequent prompts should only need to update the data. E.g.:
"""
Since the beginning of the game, the following additional events have happened:
{a} e.g. list of players joined/left
{b} e.g. list of kills
{c} e.g. list of chat messages
{instruction_to_llm}
"""

# We prune all matches that have ended or are older
# than 5 hours during database maintenance.
game_expiration = datetime.timedelta(hours=5)
api_key_deletion_leeway = datetime.timedelta(minutes=5)
db_maintenance_interval = 30.0

prompt_max_chat_messages = 15
prompt_max_kills = 15

game_id_length = 24


# Mirrored in ChatGPTBotsMutator.uc!
class SayType(StrEnum):
    ALL = "0"
    TEAM = "1"


@api_v1.on_request
async def api_v1_on_request(request: Request) -> HTTPResponse | None:
    authenticated = await auth.check_token(request, request.ctx.pg_pool)
    if not authenticated:
        return sanic.text("Unauthorized.", status=HTTPStatus.UNAUTHORIZED)

    return None


@api_v1.post("/game")
async def post_game(
        request: Request,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    try:
        # level\nserver_game_port
        data = request.body.decode("utf-8")
        level, port = data.split("\n")
        game_port = int(port)
    except Exception as e:
        logger.debug("error parsing game data", exc_info=e)
        return HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    game_id = secrets.token_hex(game_id_length)
    addr = get_remote_addr(request)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            await queries.insert_game(
                conn=conn,
                game_id=game_id,
                level=level,
                game_server_address=addr,
                game_server_port=game_port,
                start_time=now,
                stop_time=None,
            )

    # TODO: we need to do an OpenAI query here. We send initial
    #   game state to the LLM, and ask it for a short greeting message.
    async with conn.transaction():
        prompt = "TODO"
        query_id = await queries.insert_openai_query(
            conn=conn,
            time=datetime.datetime.now(tz=datetime.timezone.utc),
            game_server_address=addr,
            game_server_port=game_port,
            request_length=len(prompt),
            response_length=None,
        )
        # await client.responses.create(
        # )
        resp_len = 0  # TODO
        await queries.update_openai_query(
            conn=conn,
            query_id=query_id,
            response_length=resp_len,
        )

    greeting = ""

    return sanic.text(
        f"game_id\n{greeting}",
        status=HTTPStatus.CREATED,
        headers={"Location": f"/game/{game_id}"},  # TODO: put the full domain here?
    )


@api_v1.put("/game/<game_id>")
async def put_game(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    """Update existing game. We break a REST principle here by
    allowing partial updates in PUT, mostly because we're lazy,
    due to the fact that the existing UScript HTTP client lacks
    PATCH support.
    """
    # Assuming the only time we'll get a PUT on /game is when
    # it's marked as finished by the game server.
    # TODO: make this support other fields too if needed.

    async with pool_acquire(pg_pool) as conn:
        game = await queries.select_game(
            conn=conn,
            game_id=game_id,
        )
        if not game:
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)
        start_time: datetime.datetime = game["start_time"]

    try:
        world_time = float(request.body.decode("utf-8"))
        stop_time = start_time + datetime.timedelta(seconds=world_time)
    except Exception as e:
        logger.debug("error parsing game data", exc_info=e)
        return HTTPResponse(HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            await queries.update_game(
                conn=conn,
                game_id=game_id,
                stop_time=stop_time,
            )

    return HTTPResponse(status=HTTPStatus.NO_CONTENT)


@api_v1.post("/game/<game_id>/message")
async def post_game_message(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.pool.Pool,
        client: openai.AsyncOpenAI,
) -> HTTPResponse:
    # Validation: valid JWT, correct IP, correct port, request actually
    # comes from the correct IP. These should match the game_id!

    async with pool_acquire(pg_pool) as conn:
        game = await queries.select_game(conn, game_id)
        if not game:
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

        previous_response_id: str = game["openai_previous_response_id"]
        level: str = game["level"]

        # TODO: we need to keep track of which kills and messages have
        #       already been sent to ChatGPT? Just use send_time and
        #       kill_time variables?

        prompt = request.body.decode("utf-8")

        async with conn.transaction():
            query_id = await queries.insert_openai_query(
                conn=conn,
                time=datetime.datetime.now(tz=datetime.timezone.utc),
                game_server_address=game["game_server_address"],
                game_server_port=game["game_server_port"],
                request_length=len(prompt),
                response_length=None,
            )
            # TODO: how to best use instruction param here?
            resp = await client.responses.create(
                model=openai_model,
                input=prompt,
                previous_response_id=previous_response_id,
            )
            resp_len = len(resp.output_text)  # TODO

            await queries.update_openai_query(
                conn=conn,
                query_id=query_id,
                response_length=resp_len,
            )

    return sanic.text(
        "TODO: this is the message to post in game!",
        status=HTTPStatus.OK,
    )


@api_v1.post("/game/<game_id>/kill")
async def post_game_kill(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    async with pool_acquire(pg_pool) as conn:
        if not await queries.game_exists(conn, game_id):
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

    try:
        parts = request.body.decode("utf-8").split("\n")
    except Exception as TODO:
        # TODO: log it?
        return sanic.HTTPResponse(HTTPStatus.BAD_REQUEST)

    return sanic.HTTPResponse(status=HTTPStatus.NO_CONTENT)


@api_v1.post("/game/<game_id>/player/<player_id>")
async def put_game_player(
        request: Request,
        game_id: str,
        player_id: int,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    async with pool_acquire(pg_pool) as conn:
        if not await queries.game_exists(conn, game_id):
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

    try:
        parts = request.body.decode("utf-8").split("\n")
    except Exception as TODO:
        # TODO: log it?
        return sanic.HTTPResponse(HTTPStatus.BAD_REQUEST)

    # TODO: if player exists, send NO_CONTENT, otherwise CREATED.
    return sanic.HTTPResponse(status=HTTPStatus.NO_CONTENT)


@api_v1.post("/game/<game_id>/chat_message")
async def post_game_chat_message(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    async with pool_acquire(pg_pool) as conn:
        if not await queries.game_exists(conn, game_id):
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

    try:
        parts = request.body.decode("utf-8").split("\n")
    except Exception as TODO:
        # TODO: log it?
        return sanic.HTTPResponse(HTTPStatus.BAD_REQUEST)

    return sanic.HTTPResponse(
        status=HTTPStatus.NO_CONTENT,
        # TODO: do even want to do this? Do we need getters for these resources?
        # headers={"Location": f"/game/{game_id}/{chat_message_id}"}, # TODO: put full domain here?
    )


@api_v1.put("/game/<game_id>/objective_state")
async def put_game_objective_state(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    # Defensive check to avoid passing long strings to literal_eval.
    if len(request.body) > 2000:
        return sanic.HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        if not await queries.game_exists(conn, game_id):
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

    # TODO: maybe do proper relative DB design for this if needed?
    #       Right now it is done the quick and dirty way on purpose.
    # [["Objective A", "North"], ["Objective B", "Neutral"], ...]
    try:
        data = request.body.decode("utf-8")
        objs: list[list[str]] = ast.literal_eval(data)
        t = type(objs)  # NOTE: skipping nested type checks.
        if not t == list:
            raise ValueError(f"expected list type, got {t}")
    except Exception as e:
        logger.debug("error parsing objectives data", exc_info=e)
        return HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            await queries.upsert_game_objective_state(
                conn=conn,
                game_id=game_id,
                objectives=objs,
            )

    return sanic.HTTPResponse(status=HTTPStatus.NO_CONTENT)


@app.before_server_start
async def before_server_start(app_: App, _):
    api_key = os.environ.get("OPENAI_API_KEY")
    client = openai.AsyncOpenAI(api_key=api_key)
    app_.ctx.client = client
    app_.ext.dependency(client)

    db_url = os.environ.get("DATABASE_URL")
    pool = await asyncpg.create_pool(dsn=db_url)
    app_.ctx.pg_pool = pool
    app_.ext.dependency(pool)


@app.before_server_stop
async def before_server_stop(app_: App, _):
    if app_.ctx.client:
        await app_.ctx.client.close()
    if app_.ctx.pg_pool:
        await app_.ctx.pg_pool.close()


async def db_maintenance(stop_event: EventType) -> None:
    # TODO: try to reduce the levels of nestedness.

    pool: asyncpg.pool.Pool | None = None

    try:
        db_url = os.environ.get("DATABASE_URL")
        pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=1)

        while not stop_event.wait(db_maintenance_interval):
            async with pool_acquire(pool) as conn:
                async with conn.transaction():
                    result = await queries.delete_completed_games(conn, game_expiration)
                    logger.info("delete_completed_games: {}", result)

                async with conn.transaction():
                    result = await queries.delete_old_api_keys(conn, leeway=api_key_deletion_leeway)
                    logger.info("delete_old_api_keys: {}", result)

    except KeyboardInterrupt:
        if pool:
            await pool.close()


def db_maintenance_process(stop_event: EventType) -> None:
    asyncio.run(db_maintenance(stop_event))


@app.main_process_ready
async def main_process_ready(app_: App, _):
    app_.manager.manage(
        name="DatabaseMaintenanceProcess",
        func=db_maintenance_process,
        kwargs={"stop_event": app_.shared_ctx.db_maint_event},
        transient=True,
    )


@app.main_process_start
async def main_process_start(app_: App, _):
    db_maint_event = mp.Event()
    app_.shared_ctx.db_maint_event = db_maint_event


@app.main_process_stop
async def main_process_stop(app_: App, _):
    app_.shared_ctx.db_maint_event.set()


if __name__ == "__main__":
    app.config.INSPECTOR = True
    app.run(host="0.0.0.0", port=8080, debug=True, dev=True)
