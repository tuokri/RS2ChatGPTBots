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
import hashlib
import ipaddress
import os

import asyncpg
import click
import jwt
from asyncpg import Connection


async def async_main(
        game_server_address: ipaddress.IPv4Address,
        game_server_port: int,
        secret: str,
        issuer: str,
        audience: str,
        name: str | None = None,
) -> None:
    conn: Connection | None = None
    url = os.environ["DATABASE_URL"]
    try:
        token = jwt.encode(
            key=secret,
            algorithm="HS256",
            payload={
                "iss": issuer,
                "aud": audience,
                "sub": f"{game_server_address}:{game_server_port}",
            },
        )
        token_sha256 = hashlib.sha256(token.encode("utf-8")).digest()
        conn = await asyncpg.connect(url)
        await conn.execute(
            """
            INSERT INTO "game_server_api_key"
                (created_at, api_key_hash, game_server_address, game_server_port, name)
            VALUES ($1, $2, $3, $4, $5)
            """,
            datetime.datetime.now(tz=datetime.timezone.utc),
            token_sha256,
            game_server_address,
            game_server_port,
            name,
            timeout=10.0
        )
        print(token)
    finally:
        if conn:
            await conn.close()


@click.command()
@click.option("--game-server-address", "-a", type=ipaddress.IPv4Address, required=True)
@click.option("--game-server-port", "-p", type=int, required=True)
@click.option("--issuer", "-i", type=str, required=True)
@click.option("--audience", "-u", type=str, required=True)
@click.option("--name", "-n", type=str, default=None)
def main(
        game_server_address: str,
        game_server_port: int,
        issuer: str,
        audience: str,
        name: str | None,
) -> None:
    secret = os.environ["SANIC_SECRET"]
    asyncio.run(async_main(
        game_server_address=game_server_address,
        game_server_port=game_server_port,
        secret=secret,
        issuer=issuer,
        audience=audience,
        name=name,
    ))


if __name__ == "__main__":
    main()
