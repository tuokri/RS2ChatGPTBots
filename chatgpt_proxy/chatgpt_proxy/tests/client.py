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

import httpx
from sanic import Sanic
from sanic_testing.testing import ASGI_BASE_URL
from sanic_testing.testing import ASGI_PORT
from sanic_testing.testing import SanicASGITestClient
from sanic_testing.testing import app_call_with_return


class SpoofedSanicASGITestClient(SanicASGITestClient):
    # noinspection PyUnusedLocal
    def __init__(
            self,
            app: Sanic,
            base_url: str = ASGI_BASE_URL,
            suppress_exceptions: bool = False,
            client_ip: str | None = None,
    ):
        Sanic.test_mode = True

        app.__class__.__call__ = app_call_with_return  # type: ignore[method-assign]
        app.asgi = True

        self.sanic_app = app

        transport = httpx.ASGITransport(
            app=app,
            client=(client_ip, ASGI_PORT),
        )

        super(SanicASGITestClient, self).__init__(transport=transport, base_url=base_url)

        self.gather_request = True
        self.last_request = None
