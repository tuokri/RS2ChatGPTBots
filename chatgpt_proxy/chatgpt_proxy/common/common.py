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

import ipaddress
from types import SimpleNamespace
from typing import TypeAlias

import asyncpg
import openai
import sanic

from chatgpt_proxy.db import models


# TODO: rethink module organization.


class Context(SimpleNamespace):
    client: openai.AsyncOpenAI | None
    pg_pool: asyncpg.Pool | None


class RequestContext(SimpleNamespace):
    jwt_game_server_address: ipaddress.IPv4Address | None = None
    jwt_game_server_port: int | None = None
    game: models.Game | None = None


App: TypeAlias = sanic.Sanic[sanic.Config, Context]


class Request(sanic.Request[App, RequestContext]):
    app: App

    @staticmethod
    def make_context() -> RequestContext:
        return RequestContext()
