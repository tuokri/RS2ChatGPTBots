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

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiocache
import redis.asyncio as redis
from asyncpg import Connection
from asyncpg import Pool

from chatgpt_proxy.log import logger
from chatgpt_proxy.utils import is_prod_env

_default_acquire_timeout = 5.0

redis_namespace_db = "db"


@asynccontextmanager
async def pool_acquire(
        pool: Pool,
        timeout: float = _default_acquire_timeout,
) -> AsyncGenerator[Connection]:
    conn: Connection
    async with pool.acquire(timeout=timeout) as conn:
        yield conn


_default_cache = "redis" if is_prod_env else "memory"
_cache_method = os.getenv("CHATGPT_PROXY_CACHE_METHOD", _default_cache).lower().strip()


def setup_memory_cache() -> aiocache.SimpleMemoryCache:
    return aiocache.SimpleMemoryCache()


def setup_redis_cache() -> aiocache.RedisCache:
    redis_url = os.environ["REDIS_URL"]
    redis_client = redis.Redis.from_url(redis_url)
    return aiocache.RedisCache(
        redis_client,
        namespace=redis_namespace_db,
    )


cache: aiocache.BaseCache

if _cache_method == "redis":
    if "REDIS_URL" not in os.environ and not is_prod_env:
        logger.warning(
            f"requested DB cache method is 'redis', but no REDIS_URL is set, "
            f"falling back to in-memory cache (is_prod_env={is_prod_env})"
        )
        cache = setup_memory_cache()
    else:
        cache = setup_redis_cache()
    pass  # TODO
elif _cache_method == "memory":
    cache = setup_memory_cache()
    pass  # TODO
else:
    logger.error("invalid cache method: '{}', defaulting to memory")
    _cache_method = "memory"
    cache = setup_memory_cache()
