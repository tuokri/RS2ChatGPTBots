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
from hmac import compare_digest

import asyncpg.pool
import jwt

from chatgpt_proxy import Request
from chatgpt_proxy.db import queries
from chatgpt_proxy.utils import get_remote_addr

jwt_issuer = "ChatGPTProxy"
jwt_audience = "ChatGPTProxy"


async def check_token(request: Request, pg_pool: asyncpg.pool.Pool) -> bool:
    if not request.token:
        return False

    try:
        token = jwt.decode(
            request.token,
            request.app.config.SECRET,
            options={"require": ["exp", "iss", "sub"]},
            algorithms=["HS256"],
            audience=request.app.config.JWT_AUDIENCE,
            issuer=request.app.config.JWT_ISSUER,
        )
    except jwt.exceptions.PyJWTError:
        # logger.debug (TODO: add log module).
        return False

    # TODO: since we store API keys in DB, we should also check here
    #       that the API key provided is actually stored, and that the
    #       subject of the key is the correct server.

    # JWT subject should be IP:port.
    sub: str = token["sub"]
    a, p = sub.split(":")
    addr = ipaddress.IPv4Address(a)
    port = int(p)

    # Small extra step of security since we can't use HTTPS.
    # In any case, this is not really secure, but better than nothing.
    client_addr = get_remote_addr(request)
    if client_addr != addr:
        # TODO: log this.
        return False

    # TODO: we should cache this in memory (LRU) or diskcache.
    async with pg_pool.acquire() as conn:
        api_key = await queries.select_game_server_api_key(
            conn=conn,
            game_server_address=addr,
            game_server_port=port,
        )
        if not api_key:
            return False

        req_token_hash = hashlib.sha256(request.token.encode("utf-8")).digest()
        db_api_key_hash: bytes = api_key["api_key_hash"]
        if not compare_digest(req_token_hash, db_api_key_hash):
            # TODO: maybe log this too?
            return False

    return True
