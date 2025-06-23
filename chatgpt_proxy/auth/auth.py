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
import os

import asyncpg.pool
import jwt
from sanic import Request

jwt_issuer = "ChatGPTProxy"
jwt_audience = "ChatGPTProxy"


async def generate_token(
        secret: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        subject: str | None = None,
        payload: dict | None = None,
) -> dict:
    if secret is None:
        secret = os.environ["SANIC_SECRET"]
    if issuer is None:
        issuer = jwt_issuer
    if audience is None:
        audience = jwt_audience
    if subject is None:
        subject = ""
    if payload is None:
        payload = {}

    return jwt.encode(
        key=secret,
        algorithm="HS256",
        subject=subject,
        audience=audience,
        issuer=issuer,
        payload=payload,
    )


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

    # TODO: we should cache this in memory (LRU) or diskcache.
    async with pg_pool.acquire() as conn:
        pass

    return True

# def protected(wrapped):
#     def decorator(f: Callable[[Request, Any, Any], Awaitable[HTTPResponse]]):
#         @functools.wraps(f)
#         async def decorated_function(request: Request, *args, **kwargs) -> HTTPResponse:
#             is_authenticated = check_token(request)
#
#             if is_authenticated:
#                 response = await f(request, *args, **kwargs)
#                 return response
#             else:
#                 return sanic.text("Unauthorized.", HTTPStatus.UNAUTHORIZED)
#
#         return decorated_function
#
#     return decorator(wrapped)
