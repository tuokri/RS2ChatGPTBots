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

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TypeAlias

import openai
import sanic
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse

api_v1 = Blueprint("api", version_prefix="/api/v", version=1)


class Context(SimpleNamespace):
    client: openai.AsyncOpenAI | None


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
# - /reset_context: (context) reset all context data.
# - /base_prompt: (context) appended in front of all requests to the LLM.

# TODO: example prompt.
"""
{base_prompt}

The game currently contains the following players
"""


@dataclass
class MessageContext:
    pass


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
    app.ctx.client = client
    app_.ext.dependency(client)


@app.before_server_stop
async def before_server_stop(app_: App, _):
    if app_.ctx.client:
        await app_.ctx.client.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True, dev=True)
