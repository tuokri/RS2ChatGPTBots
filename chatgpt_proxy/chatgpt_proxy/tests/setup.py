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
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

import chatgpt_proxy


class Ignored:
    pass


ignored = Ignored()

test_sanic_secret = "dummy"
test_db = "chatgpt_proxy_tests"
default_db_url = "postgresql://postgres:postgres@localhost:5432"
db_url = default_db_url
db_base_url = default_db_url
db_test_url = f"{db_url.rstrip("/")}/chatgpt_proxy_tests"
steam_web_api_key = "dummy_steam_web_api_key"

_root_path = Path(chatgpt_proxy.__file__).resolve().parent
_pkg_path_db = _root_path / "db/"
_pkg_path_tests = _root_path / "tests/"

assert _root_path.exists()
assert _pkg_path_db.exists()
assert _pkg_path_tests.exists()

_default_db_timeout = 30.0


async def initialize_test_db(
        conn: asyncpg.Connection,
        timeout: float | None = _default_db_timeout
):
    init_db_sql = (_pkg_path_db / "db.sql").read_text()
    await conn.execute(init_db_sql, timeout=timeout)


async def seed_test_db(
        conn: asyncpg.Connection,
        timeout: float | None = _default_db_timeout
):
    seed_db_sql = (_pkg_path_tests / "seed.sql").read_text()
    await conn.execute(seed_db_sql, timeout=timeout)


async def drop_test_db(
        conn: asyncpg.Connection,
        timeout: float | None = _default_db_timeout
):
    await conn.execute(
        f"DROP DATABASE IF EXISTS {test_db} WITH (FORCE)",
        timeout=timeout,
    )


# TODO: this is sketchy as fuck, try to come up with a better way?
def common_test_setup(
        db_url_: str | Ignored = ignored,
        test_db_: str | Ignored = ignored,
        db_test_url_: str | Ignored = ignored,
        steam_web_api_key_: str | Ignored = ignored,
        test_sanic_secret_: str | Ignored = ignored,
) -> None:
    global db_url
    global db_base_url
    global db_test_url
    global test_db
    global steam_web_api_key
    global test_sanic_secret

    if db_url_ is not ignored:
        db_url = db_url_
    else:
        # NOTE: avoid messing up DB URL if this is called multiple times
        # from different tests!
        db_url = os.environ.get("DATABASE_URL", default_db_url)
        parts = urlparse(db_url)
        parts = parts._replace(path="")
        db_base_url = parts.geturl()

    if db_test_url_ is not ignored:
        db_test_url = db_test_url_
    else:
        # NOTE: avoid messing up DB URL if this is called multiple times
        # from different tests!
        db_test_url = f"{db_base_url.rstrip("/")}/chatgpt_proxy_tests"

    if test_db_ is not ignored:
        test_db = test_db_
    if steam_web_api_key_ is not ignored:
        steam_web_api_key = steam_web_api_key_
    if test_sanic_secret_ is not ignored:
        test_sanic_secret = test_sanic_secret_

    os.environ["SANIC_SECRET"] = test_sanic_secret
    os.environ["OPENAI_API_KEY"] = "dummy"
    os.environ["DATABASE_URL"] = db_test_url
    os.environ["STEAM_WEB_API_KEY"] = steam_web_api_key
