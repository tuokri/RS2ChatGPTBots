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

"""Provides authentication and authorization for the chatgpt_proxy API server."""

import datetime
import hashlib
import ipaddress
import os
from functools import wraps
from hmac import compare_digest
from http import HTTPStatus
from inspect import isawaitable
from typing import Callable

import aiocache
import asyncpg
import httpx
import jwt
import sanic

from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries
from chatgpt_proxy.log import logger
from chatgpt_proxy.types import Request
from chatgpt_proxy.utils import get_remote_addr

jwt_issuer = "ChatGPTProxy"
jwt_audience = "ChatGPTProxy"

_server_list_url = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"

_steam_web_api_key: str | None = None


def load_config() -> None:
    global _steam_web_api_key
    _steam_web_api_key = os.environ.get("STEAM_WEB_API_KEY", None)


load_config()

ttl_is_real_game_server = datetime.timedelta(minutes=60).total_seconds()


# TODO: waiting for updated aiocache + valkey-glide support on Windows!
#   - In the meanwhile, only use memory cache!
#   - See pyproject.toml for more details!
@aiocache.cached(
    # cache=app_cache,
    cache=aiocache.Cache.MEMORY,
    ttl=ttl_is_real_game_server,
    # NOTE: Only cache the result if the server was successfully verified.
    skip_cache_func=lambda x: x is False,
)
async def is_real_game_server(
        client: httpx.AsyncClient,
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
) -> bool:
    try:
        resp = await client.get(
            _server_list_url,
            params={
                "key": _steam_web_api_key,
                "filter": f"\\gamedir\\rs2\\gameaddr\\{game_server_address}:{game_server_port}",
                # TODO: limit param would speed up things, or would it?
            },
        )
        resp.raise_for_status()
        servers = resp.json()["response"]["servers"]

        if not servers:
            logger.debug("Steam Web API returned no servers for {}:{}",
                         game_server_address, game_server_port)
            return False

        return True
    except Exception as e:
        logger.debug("unable to verify {}:{} is a real RS2 server: {}: {}",
                     game_server_address, game_server_port, type(e).__name__, e)
        return False


async def check_token(request: Request, pg_pool: asyncpg.Pool) -> bool:
    if not request.token:
        logger.debug("JWT validation failed: no token")
        return False

    try:
        token = jwt.decode(
            jwt=request.token,
            key=request.app.config.SECRET,
            options={"require": ["exp", "iss", "sub", "aud"]},
            algorithms=["HS256"],
            audience=request.app.config.JWT_AUDIENCE,
            issuer=request.app.config.JWT_ISSUER,
        )
    except jwt.exceptions.PyJWTError as e:
        logger.debug("JWT validation failed: {}: {}", type(e).__name__, e)
        return False

    # JWT subject should be IP:port.
    sub: str = token["sub"]
    a, p = sub.split(":")
    addr = ipaddress.IPv4Address(a)
    port = int(p)
    logger.debug("token addr:port: {}:{}", addr, port)

    # Small extra step of security since we can't use HTTPS.
    # In any case, this is not really secure, but better than nothing.
    client_addr = get_remote_addr(request)
    logger.debug("client_addr: {}", client_addr)
    if client_addr != addr:
        logger.debug("JWT validation failed: (client_addr != addr): {} != {}", client_addr, addr)
        return False

    # TODO: we should cache this in memory (LRU) or diskcache.
    async with pool_acquire(pg_pool) as conn:
        api_key = await queries.select_game_server_api_key(
            conn=conn,
            game_server_address=addr,
            game_server_port=port,
        )

        logger.debug("api_key: {}", api_key)

        if not api_key:
            logger.debug("JWT validation failed: no API key for {}:{}", addr, port)
            return False

        req_token_hash = hashlib.sha256(request.token.encode("utf-8")).digest()
        db_api_key_hash: bytes = api_key["api_key_hash"]
        if not compare_digest(req_token_hash, db_api_key_hash):
            logger.debug("JWT validation failed: stored hash does not match token hash")
            return False

    if _steam_web_api_key is None:
        logger.warning("Steam Web API key is not set, "
                       "unable to verify server is a real RS2 server")
    else:
        ok = await is_real_game_server(
            request.app.ctx.http_client,  # type: ignore[arg-type]
            addr,
            port,
        )
        if not ok:
            logger.debug("JWT validation failed: server is not a real RS2 server "
                         "according to Steam Web API")
            return False

    request.ctx.jwt_game_server_port = port
    request.ctx.jwt_game_server_address = addr

    return True


def check_and_inject_game(func: Callable) -> Callable:
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        async def game_owner_checked_handler(
                request: Request,
                game_id: str,
                *args,
                **kwargs,
        ) -> sanic.HTTPResponse:
            if ((request.ctx.jwt_game_server_address is None)
                    or (request.ctx.jwt_game_server_port is None)
            ):
                logger.debug(
                    "cannot verify game owner: jwt_game_server_address={}, jwt_game_server_port={}",
                    request.ctx.jwt_game_server_address,
                    request.ctx.jwt_game_server_port,
                )
                return sanic.HTTPResponse("Unauthorized.", status=HTTPStatus.UNAUTHORIZED)

            async with pool_acquire(request.app.ctx.pg_pool) as conn:
                game = await queries.select_game(conn=conn, game_id=game_id)
                if not game:
                    logger.debug("no game found for game_id: {}", game_id)
                    return sanic.HTTPResponse(status=HTTPStatus.NOT_FOUND)

                if game.game_server_address != request.ctx.jwt_game_server_address:
                    logger.debug(
                        "unauthorized: token address != DB address: {} != {}",
                        game.game_server_address,
                        request.ctx.jwt_game_server_address,
                    )
                    return sanic.HTTPResponse("Unauthorized.", status=HTTPStatus.UNAUTHORIZED)

                if game.game_server_port != request.ctx.jwt_game_server_port:
                    logger.debug(
                        "unauthorized: token port != DB port: {} != {}",
                        game.game_server_port,
                        request.ctx.jwt_game_server_port,
                    )
                    return sanic.HTTPResponse("Unauthorized.", status=HTTPStatus.UNAUTHORIZED)

                request.ctx.game = game

            response = f(request, game_id=game_id, *args, **kwargs)
            if isawaitable(response):
                return await response
            return response  # pragma: no coverage

        return game_owner_checked_handler

    return decorator(func)
