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

import hashlib
import ipaddress
from functools import wraps
from hmac import compare_digest
from http import HTTPStatus
from inspect import isawaitable
from typing import Callable

import asyncpg
import jwt
import sanic

from chatgpt_proxy.db import pool_acquire
from chatgpt_proxy.db import queries
from chatgpt_proxy.log import logger
from chatgpt_proxy.types import Request
from chatgpt_proxy.utils import get_remote_addr

jwt_issuer = "ChatGPTProxy"
jwt_audience = "ChatGPTProxy"


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

    # TODO: since we store API keys in DB, we should also check here
    #       that the API key provided is actually stored, and that the
    #       subject of the key is the correct server.

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

    # TODO: consider, we could also do an A2S query or Steam Web API query,
    #   (and cache it) to verify that the server truly exists and is an RS2 server.
    #   But is this too much extra effort for a very minimal security gain?

    # TODO: double-check later that it's safe to assign these at this point!
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

            async with (pool_acquire(request.app.ctx.pg_pool) as conn):
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

            response = f(request, game_id, *args, **kwargs)
            if isawaitable(response):
                return await response
            return response

        return game_owner_checked_handler

    return decorator(func)
