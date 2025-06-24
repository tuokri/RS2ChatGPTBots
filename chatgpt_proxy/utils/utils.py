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

from chatgpt_proxy import Request

is_prod_env: bool = "FLY_APP_NAME" in os.environ


def get_remote_addr(request: Request) -> ipaddress.IPv4Address:
    """Ignoring IPv6 since Steam game servers should always
    be IPv4, and this API only expects requests from Steam GSs.
    """
    if is_prod_env:
        return ipaddress.IPv4Address(request.headers["Fly-Client-IP"])
    else:
        return ipaddress.IPv4Address(request.remote_addr)
