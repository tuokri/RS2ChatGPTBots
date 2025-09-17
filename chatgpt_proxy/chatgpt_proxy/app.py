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

import asyncio
import dataclasses
import datetime
import multiprocessing as mp
import os
import secrets
from http import HTTPStatus
from multiprocessing.synchronize import Event as EventType
from pprint import pprint

import asyncpg
import httpx
import openai
import sanic
from py_markdown_table.markdown_table import markdown_table
from sanic import Blueprint
from sanic.response import HTTPResponse

from chatgpt_proxy.auth import auth
from chatgpt_proxy.auth import check_and_inject_game
from chatgpt_proxy.auth import is_real_game_server
from chatgpt_proxy.cache import app_cache
from chatgpt_proxy.cache import db_cache
from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries
from chatgpt_proxy.db.models import GameObjectiveState
from chatgpt_proxy.db.models import SayType
from chatgpt_proxy.db.models import Team
from chatgpt_proxy.log import logger
from chatgpt_proxy.types import App
from chatgpt_proxy.types import Context
from chatgpt_proxy.types import Request
from chatgpt_proxy.utils import get_remote_addr
from chatgpt_proxy.utils import is_prod_env
from chatgpt_proxy.utils import utcnow

# TODO: This breaks with nest_asyncio, which is also unmaintained!
# if platform.system() == "Windows":
#     # noinspection PyUnresolvedReferences
#     import winloop  # type: ignore[import-not-found]
#
#     winloop.install()

# TODO: need to come up with a more consistent way for logging errors
#   from request validation, etc.:
#       - Log basic error info at info level.
#       - Log the stack trace at debug level (use Sentry for this in prod?)
#       - Consider Sentry for logging all other unhandled errors!

api_v1 = Blueprint("api", version_prefix="/api/v", version=1)


def db_maintenance_process(stop_event: EventType) -> None:
    asyncio.run(db_maintenance(stop_event))


def refresh_steam_web_api_cache_process(stop_event: EventType) -> None:
    asyncio.run(refresh_steam_web_api_cache(stop_event))


max_ast_literal_eval_size = 1000


def make_api_v1_app(name: str = "ChatGPTProxy") -> App:
    _app: App = sanic.Sanic(
        name,
        ctx=Context(),
        request_class=Request,  # type: ignore[arg-type]
    )
    # We don't expect UScript side to send large requests.
    _app.config.REQUEST_MAX_SIZE = 1500
    _app.config.REQUEST_MAX_HEADER_SIZE = 1500
    _app.config.OAS = not is_prod_env
    _app.config.SECRET = os.environ["SANIC_SECRET"]
    _app.config.JWT_ISSUER = auth.jwt_issuer
    _app.config.JWT_AUDIENCE = auth.jwt_audience

    @_app.main_process_ready
    async def main_process_ready(app_: App, _):
        app_.manager.manage(
            name="DatabaseMaintenanceProcess",
            func=db_maintenance_process,
            kwargs={"stop_event": app_.shared_ctx.bg_process_event},
            transient=True,
        )
        app_.manager.manage(
            "SteamWebAPICacheRefreshProcess",
            func=refresh_steam_web_api_cache_process,
            kwargs={"stop_event": app_.shared_ctx.bg_process_event},
            transient=True,
        )

    @_app.main_process_start
    async def main_process_start(app_: App, _):
        bg_process_event = mp.Event()
        app_.shared_ctx.bg_process_event = bg_process_event

    @_app.main_process_stop
    async def main_process_stop(app_: App, _):
        app_.shared_ctx.bg_process_event.set()

    @_app.before_server_start
    async def before_server_start(app_: App, _):
        api_key = os.environ.get("OPENAI_API_KEY")
        client = openai.AsyncOpenAI(api_key=api_key)
        app_.ctx.client = client
        app_.ext.dependency(client)

        db_url = os.environ.get("DATABASE_URL")
        pool = await asyncpg.create_pool(dsn=db_url)
        app_.ctx.pg_pool = pool
        app_.ext.dependency(pool)

        app_.ctx.http_client = httpx.AsyncClient()
        app_.ext.dependency(app_.ctx.http_client)

    @_app.before_server_stop
    async def before_server_stop(app_: App, _):
        if app_.ctx.client:
            await app_.ctx.client.close()
        if app_.ctx.pg_pool:
            await app_.ctx.pg_pool.close()
        if app_.ctx.http_client:
            await app_.ctx.http_client.aclose()

        await app_cache.close()
        await db_cache.close()

    _app.blueprint(api_v1)

    return _app


# TODO: dynamic model selection?
openai_model = "gpt-5-nano"
openai_timeout = 60.0  # TODO: this might be way too low?

prompt_max_game_chat_msgs = 30
prompt_max_game_kills = 30

# TODO: example prompt (the first one per game session).
# TODO: this should only be sent from the UScript side after a small
#       delay to allow the game state to "stabilize".
base_prompt_initial = """
You are a TODO.

This is the beginning of a new game. The game currently contains
the following players:
{markdown_scoreboard_table}

The last {num_kills} kills scored during the game are the
following (in ascending chronological order):
{markdown_kills_table}}

The last {num_chat_msgs} chat messages sent during the game are the
following (ascending in chronological order):
{markdown_chat_msgs_table}}

{initial_instruction}
"""

# TODO: subsequent prompts should only need to update the data. E.g.:
base_prompt_consecutive = """
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
steam_web_api_cache_refresh_interval = datetime.timedelta(minutes=30).total_seconds()

game_id_length = 24


def format_base_prompt_initial(
        markdown_scoreboard_table: str,
        markdown_kills_table: str,
        markdown_chat_msgs_table: str,
        initial_instruction: str,
) -> str:
    return base_prompt_initial.format(
        markdown_scoreboard_table=markdown_scoreboard_table,
        markdown_kills_table=markdown_kills_table,
        markdown_chat_msgs_table=markdown_chat_msgs_table,
        initial_instruction=initial_instruction,
    )


async def get_kills_markdown_table(
        conn: asyncpg.Connection,
        game_id: str,
        from_time: datetime.datetime,
) -> str:
    candidate_kills = await queries.select_game_kills(
        conn=conn,
        game_id=game_id,
        kill_time_from=from_time,
        limit=prompt_max_game_kills,
    )
    pprint(candidate_kills)

    kills_table = ""
    if candidate_kills:
        kills_table = markdown_table([
            kill.as_markdown_dict()
            for kill in candidate_kills
        ]).get_markdown()
        pprint(kills_table)

    return kills_table


async def get_chat_messages_markdown_table(
        conn: asyncpg.Connection,
        from_time: datetime.datetime,
) -> str:
    candidate_msgs = await queries.select_game_chat_messages(
        conn=conn,
        send_time_from=from_time,
        limit=prompt_max_game_chat_msgs,
    )
    pprint(candidate_msgs)

    msgs_table = ""
    if candidate_msgs:
        msgs_table = markdown_table([
            msg.as_markdown_dict()
            for msg in candidate_msgs
        ]).get_markdown()
        pprint(msgs_table)

    return msgs_table


@api_v1.get("/game/<game_id:str>")
async def get_game(
        _: Request,
        game_id: str,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    # TODO: do we need these for anything other than testing?
    if is_prod_env:
        return HTTPResponse(status=HTTPStatus.NOT_FOUND)

    async with pool_acquire(pg_pool) as conn:
        db_game = await queries.select_game(conn=conn, game_id=game_id)

        if not db_game:
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

        game_dict = dataclasses.asdict(db_game)
        game_dict["start_time"] = db_game.start_time.isoformat()
        stop_time = db_game.stop_time
        if stop_time:
            game_dict["stop_time"] = stop_time.isoformat()
        game_dict["game_server_address"] = str(db_game.game_server_address)

        return sanic.json(game_dict)


@api_v1.post("/game")
async def post_game(
        request: Request,
        pg_pool: asyncpg.Pool,
        client: openai.AsyncOpenAI,
) -> HTTPResponse:
    try:
        data = request.body.decode("utf-8")
        level, port = data.split("\n")
        game_port = int(port)
    except Exception as e:
        logger.debug("error parsing game data: {}: {}", type(e).__name__, e)
        return HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    now = utcnow()
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
                openai_previous_response_id=None,
            )

        # TODO: Send initial game state to the LLM, and ask it for a short greeting message.
        async with conn.transaction():
            prompt = "Write a short poem of 100 letters or less."  # TODO
            openai_resp = await client.responses.create(
                model=openai_model,
                input=prompt,
                timeout=openai_timeout,
            )
            await queries.insert_openai_query(
                game_id=game_id,
                conn=conn,
                time=utcnow(),
                game_server_address=addr,
                game_server_port=game_port,
                request_length=len(prompt),
                response_length=len(openai_resp.output_text),
                openai_response_id=openai_resp.id,
            )

    greeting = openai_resp.output_text

    return sanic.text(
        f"{game_id}\n{greeting}",
        status=HTTPStatus.CREATED,
        # TODO: use url_for!
        headers={"Location": f"{api_v1.version_prefix}{api_v1.version}/game/{game_id}"},
        # TODO: put the full domain here?
    )


@api_v1.put("/game/<game_id:str>")
@check_and_inject_game
async def put_game(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    """Update existing game. We break a REST principle here by
    allowing partial updates in PUT, mostly because we're lazy,
    due to the fact that the existing UScript HTTP client lacks
    PATCH support.
    """
    # Assuming the only time we'll get a PUT on /game is when
    # it's marked as finished by the game server.
    # TODO: make this support other fields too if needed.

    start_time = request.ctx.game.start_time

    try:
        world_time = float(request.body.decode("utf-8"))
        stop_time = start_time + datetime.timedelta(seconds=world_time)
    except Exception as e:
        logger.debug("error parsing game data: {}: {}", type(e).__name__, e)
        return HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            await queries.update_game(
                conn=conn,
                game_id=game_id,
                stop_time=stop_time,
            )

    return HTTPResponse(status=HTTPStatus.NO_CONTENT)


@api_v1.post("/game/<game_id:str>/message")
@check_and_inject_game
async def post_game_message(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.Pool,
        client: openai.AsyncOpenAI,
) -> HTTPResponse:
    # TODO: full implementation! Prompt building!

    game = request.ctx.game

    previous_response_id: str | None = game.openai_previous_response_id
    if previous_response_id is None:
        logger.warning("unable to handle request for game with no openai_previous_response_id")
        return HTTPResponse(status=HTTPStatus.SERVICE_UNAVAILABLE)

    level: str = game.level

    async with pool_acquire(pg_pool) as conn:
        previous_query = await queries.select_openai_query(
            conn=conn,
            openai_response_id=previous_response_id,
        )
        if not previous_query:
            logger.warning("cannot find OpenAI query for id: {}", previous_response_id)
            return HTTPResponse(status=HTTPStatus.SERVICE_UNAVAILABLE)

        try:
            data_in = request.body.decode("utf-8").split("\n")
            say_type = SayType(data_in[0])
            say_team = Team(data_in[1])
            say_name = data_in[2]
            prompt_in = data_in[3]
        except Exception as e:
            logger.info("error parsing game message data: {}: {}", type(e).__name__, e)
            # TODO: debug log stack trace or something?
            return HTTPResponse(status=HTTPStatus.BAD_REQUEST)

        # TODO: have some maximum upper limit for total prompt length.
        prompt = ""  # TODO

        kills_table = await get_kills_markdown_table(
            conn=conn,
            game_id=game.id,
            from_time=previous_query.time,
        )
        msgs_table = await get_chat_messages_markdown_table(
            conn=conn,
            from_time=previous_query.time,
        )

        # TODO: format prompt here, taking maximum length into account!
        #   E.g.: (rough drafts):
        # Format kills table -> remove length from remaining budget.
        # Calculate budget for remaining fields (weighted budgets).
        max_chat_messages_to_add = 0  # Calculate budget.
        max_kills_to_add = 0  # Calculate budget.

        async with conn.transaction():
            # TODO: how to best use instruction param here?
            resp = await client.responses.create(
                model=openai_model,
                input=prompt,
                previous_response_id=previous_response_id,
                timeout=openai_timeout,
            )
            await queries.insert_openai_query(
                conn=conn,
                game_id=game_id,
                time=utcnow(),
                game_server_address=game.game_server_address,
                game_server_port=game.game_server_port,
                request_length=len(prompt),
                response_length=len(resp.output_text),
                openai_response_id=resp.id,
            )

    msg = resp.output_text.replace("\n", " ")
    resp_data = f"{say_type}\n{say_team}\n{say_name}\n{msg}"

    return sanic.text(
        resp_data,
        status=HTTPStatus.OK,
    )


@api_v1.post("/game/<game_id:str>/kill")
@check_and_inject_game
async def post_game_kill(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    game = request.ctx.game

    try:
        parts = request.body.decode("utf-8").split("\n")
        world_time = float(parts[0])
        killer_name = parts[1]
        victim_name = parts[2]
        killer_team = Team(parts[3])
        victim_team = Team(parts[4])
        damage_type = parts[5]
        kill_distance_m = float(parts[6])

        kill_time = game.start_time + datetime.timedelta(seconds=world_time)
    except Exception as e:
        logger.debug("failed to parse game kill data: {}: {}", type(e).__name__, e)
        return sanic.HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            await queries.insert_game_kill(
                conn=conn,
                game_id=game_id,
                kill_time=kill_time,
                killer_name=killer_name,
                victim_name=victim_name,
                killer_team=killer_team,
                victim_team=victim_team,
                damage_type=damage_type,
                kill_distance_m=kill_distance_m,
            )

    return sanic.HTTPResponse(status=HTTPStatus.NO_CONTENT)


@api_v1.put("/game/<game_id:str>/player/<player_id:int>")
@check_and_inject_game
async def put_game_player(
        request: Request,
        game_id: str,
        player_id: int,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    _ = request.ctx.game  # TODO: needed here?

    try:
        parts = request.body.decode("utf-8").split("\n")
        name = parts[0]
        team = Team(parts[1])
        score = int(parts[2])
    except Exception as e:
        logger.debug("failed to parse game player data: {}: {}", type(e).__name__, e)
        return sanic.HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            created = await queries.upsert_game_player(
                conn=conn,
                game_id=game_id,
                player_id=player_id,
                name=name,
                team_index=int(team),
                score=score,
            )

    status = HTTPStatus.CREATED if created else HTTPStatus.NO_CONTENT
    return sanic.HTTPResponse(status=status)


@api_v1.delete("/game/<game_id:str>/player/<player_id:int>")
@check_and_inject_game
async def delete_game_player(
        _: Request,
        game_id: str,
        player_id: int,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    async with pool_acquire(pg_pool) as conn:
        if not await queries.game_player_exists(
                conn=conn,
                game_id=game_id,
                player_id=player_id,
        ):
            return HTTPResponse(status=HTTPStatus.NOT_FOUND)

        async with conn.transaction():
            await queries.delete_game_player(
                conn=conn,
                game_id=game_id,
                player_id=player_id,
            )

    return HTTPResponse(status=HTTPStatus.NO_CONTENT)


@api_v1.post("/game/<game_id:str>/chat_message")
@check_and_inject_game
async def post_game_chat_message(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    _ = request.ctx.game  # TODO: needed here?

    try:
        parts = request.body.decode("utf-8").split("\n")
        player_name = parts[0]
        player_team = Team(parts[1])
        say_type = SayType(parts[2])
        msg = parts[3]
        async with pool_acquire(pg_pool) as conn:
            async with conn.transaction():
                await queries.insert_game_chat_message(
                    conn=conn,
                    game_id=game_id,
                    message=msg,
                    send_time=utcnow(),
                    sender_name=player_name,
                    sender_team=player_team,
                    channel=say_type,
                )
    except Exception as e:
        logger.debug("failed to parse chat message data: {}: {}", type(e).__name__, e)
        return sanic.HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    return sanic.HTTPResponse(
        status=HTTPStatus.NO_CONTENT,
        # TODO: do even want to do this? Do we need getters for these resources?
        # headers={"Location": f"/game/{game_id}/{chat_message_id}"}, # TODO: put full domain here?
    )


@api_v1.put("/game/<game_id:str>/objective_state")
@check_and_inject_game
async def put_game_objective_state(
        request: Request,
        game_id: str,
        pg_pool: asyncpg.Pool,
) -> HTTPResponse:
    # Defensive check to avoid passing long strings to literal_eval.
    if len(request.body) > max_ast_literal_eval_size:
        return sanic.HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    _ = request.ctx.game  # TODO: needed here?

    # TODO: maybe do proper relative DB design for this if needed?
    #       Right now it is done the quick and dirty way on purpose.
    # [("Objective A",0),("Objective B",1),...]
    try:
        data = request.body.decode("utf-8")
        if not data:
            raise ValueError("no objective state data")

        obj_state = GameObjectiveState.from_wire_format(
            game_id=game_id,
            wire_format_data=data,
        )

    except Exception as e:
        logger.debug("error parsing objectives data: {}: {}", type(e).__name__, e)
        logger.opt(exception=e).debug("")  # TODO: should use this more!
        return HTTPResponse(status=HTTPStatus.BAD_REQUEST)

    async with pool_acquire(pg_pool) as conn:
        async with conn.transaction():
            created = await queries.upsert_game_objective_state(
                conn=conn,
                state=obj_state,
            )

    status = HTTPStatus.CREATED if created else HTTPStatus.NO_CONTENT
    return sanic.HTTPResponse(status=status)


async def db_maintenance(stop_event: EventType) -> None:
    # TODO: try to reduce the levels of nestedness.

    pool: asyncpg.Pool | None = None

    try:
        db_url = os.environ.get("DATABASE_URL")
        pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=1)

        while not stop_event.wait(db_maintenance_interval):
            async with pool_acquire(pool) as conn:
                async with conn.transaction():
                    result = await queries.delete_completed_games(conn, game_expiration)
                    logger.info("delete_completed_games: {}", result)

                async with conn.transaction():
                    result = await queries.delete_old_api_keys(
                        conn,
                        leeway=api_key_deletion_leeway,
                    )
                    logger.info("delete_old_api_keys: {}", result)

    except KeyboardInterrupt:
        if pool:
            await pool.close()


async def refresh_steam_web_api_cache(stop_event: EventType) -> None:
    pool: asyncpg.Pool | None = None

    try:
        db_url = os.environ.get("DATABASE_URL")
        pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=1)

        while not stop_event.wait(steam_web_api_cache_refresh_interval):
            async with pool_acquire(pool) as conn:
                api_keys = await queries.select_game_server_api_keys(conn)
                logger.info("refreshing Steam Web API cache for {} keys", len(api_keys))
            async with httpx.AsyncClient(timeout=30.0) as client:
                tasks = [
                    is_real_game_server(
                        client=client,
                        game_server_address=api_key["game_server_address"],
                        game_server_port=api_key["game_server_port"],
                    )
                    for api_key in api_keys
                ]
                await asyncio.gather(*tasks)

    except KeyboardInterrupt:
        await app_cache.close()
        if pool:
            await pool.close()


@api_v1.on_request
async def api_v1_on_request(request: Request) -> HTTPResponse | None:
    authenticated = await auth.check_token(request, request.app.ctx.pg_pool)
    if not authenticated:
        return sanic.text("Unauthorized.", status=HTTPStatus.UNAUTHORIZED)

    return None


app = make_api_v1_app()

if __name__ == "__main__":
    app.config.INSPECTOR = True
    logger.level("DEBUG")
    app.run(host="0.0.0.0", port=8080, debug=True, dev=True, access_log=True)
