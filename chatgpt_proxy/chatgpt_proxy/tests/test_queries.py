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

import datetime

from chatgpt_proxy.db import queries


def test_build_update_game_query():
    game_id = "123"
    stop_time = datetime.datetime(
        year=2025,
        day=30,
        month=6,
        hour=13,
        minute=16,
        second=0,
        tzinfo=datetime.timezone.utc,
    )
    resp_id = "xxx"

    query = queries.update_game_query(
        game_id=game_id,
        stop_time=stop_time,
        openai_previous_response_id=resp_id,
    )
    print(str(query))

    query = queries.update_game_query(
        game_id=game_id,
        stop_time=stop_time,
        openai_previous_response_id=queries.IGNORED,
    )
    print(str(query))

    query = queries.update_game_query(
        game_id=game_id,
        stop_time=queries.IGNORED,
        openai_previous_response_id=resp_id,
    )
    print(str(query))
