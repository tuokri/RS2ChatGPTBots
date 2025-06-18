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
import datetime
import ipaddress
import multiprocessing as mp
import os
import secrets
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TypeAlias

import asyncpg
import openai
import sanic
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse

from chatgpt_proxy.db import queries

api_v1 = Blueprint("api", version_prefix="/api/v", version=1)


class Context(SimpleNamespace):
    client: openai.AsyncOpenAI | None
    pg_pool: asyncpg.pool.Pool | None


App: TypeAlias = sanic.Sanic[sanic.Config, Context]

app: App = sanic.Sanic(__name__, ctx=Context())
app.blueprint(api_v1)
# app.config.OAS = False

# Rough API design:
# - /message: to "fire" actual message request -> returns a chat message to send in game.
#    * all context data is taken into account
# - /message_history: (context) post here to keep a short log of previous chat messages.
# - /players: (context) post/delete here to keep the current player list up to date.
# - /kills: (context) post here to keep a short log of previous kills.
# - /base_prompt: (context) appended in front of all requests to the LLM.

# TODO: example prompt.
"""
{base_prompt}

The game currently contains the following players
"""

# We prune all matches that have ended or are older
# than 5 hours during database maintenance.
game_expiration = datetime.timedelta(hours=5)


@dataclass
class MessageContext:
    pass


@api_v1.post("/game")
async def post_game(
        request: Request,
        pg_pool: asyncpg.pool.Pool,
) -> HTTPResponse:
    # TODO: check some sorta JWT here!

    game_id = secrets.token_hex(32)

    addr = ipaddress.IPv4Address("127.0.0.1")

    async with pg_pool.acquire() as conn:
        async with conn.transaction():
            await queries.insert_game(
                conn=conn,
                game_id=game_id,
                game_server_address=addr,
                game_server_port=6969,
                start_time=datetime.datetime.now(tz=datetime.timezone.utc),
                stop_time=None,
            )

    return sanic.text(game_id)


@api_v1.post("/game/<game_id>/message")
async def post_game_message(
        request: Request,
        game_id: str,
        client: openai.AsyncOpenAI,
) -> HTTPResponse:
    return sanic.text("TODO")


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


async def db_maintenance(stop_event: mp.Event) -> None:
    # TODO: try to reduce the levels of nestedness.

    pool: asyncpg.pool.Pool | None = None

    try:
        db_url = os.environ.get("DATABASE_URL")
        pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=1)

        while not stop_event.wait(30.0):
            async with pool.acquire() as conn:
                async with conn.transaction():
                    result = await queries.delete_completed_games(conn, game_expiration)
                    print(result)

    except KeyboardInterrupt:
        if pool:
            await pool.close()


def db_maintenance_process(stop_event: mp.Event) -> None:
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
    app.run(host="0.0.0.0", port=8080, debug=True, dev=True)
