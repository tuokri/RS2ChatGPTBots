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

"""Common and shared project type definitions."""

import ipaddress
from types import SimpleNamespace
from typing import TypeAlias

import asyncpg
import httpx
import openai
import sanic

from chatgpt_proxy.db import models


class Context(SimpleNamespace):
    _client: openai.AsyncOpenAI | None
    _pg_pool: asyncpg.Pool | None
    _http_client: httpx.AsyncClient | None

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            raise RuntimeError("Context client is None")
        return self._client

    @client.setter
    def client(self, value: openai.AsyncOpenAI):
        self._client = value

    @property
    def pg_pool(self) -> asyncpg.Pool:
        if self._pg_pool is None:
            raise RuntimeError("Context pg_pool is None")
        return self._pg_pool

    @pg_pool.setter
    def pg_pool(self, value: asyncpg.Pool):
        self._pg_pool = value

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            raise RuntimeError("Context http_client is None")
        return self._http_client

    @http_client.setter
    def http_client(self, value: httpx.AsyncClient):
        self._http_client = value


class RequestContext(SimpleNamespace):
    jwt_game_server_address: ipaddress.IPv4Address | None = None
    jwt_game_server_port: int | None = None
    _game: models.Game | None = None

    @property
    def game(self) -> models.Game:
        if self._game is None:
            raise RuntimeError("RequestContext game is None")
        return self._game

    @game.setter
    def game(self, value: models.Game):
        self._game = value


App: TypeAlias = sanic.Sanic[sanic.Config, Context]


class Request(sanic.Request[App, RequestContext]):
    app: App

    @staticmethod
    def make_context() -> RequestContext:
        return RequestContext()
