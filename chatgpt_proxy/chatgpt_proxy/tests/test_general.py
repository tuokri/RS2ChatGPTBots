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

import sys
from pathlib import Path

import chatgpt_proxy

version_file = Path(chatgpt_proxy.__file__).parent / "_version.py"


# TODO: is this test suite too flaky?

def test_version() -> None:
    print(f"{chatgpt_proxy.__version__=}")
    if version_file.exists():
        assert chatgpt_proxy.__version__ != "unknown"
    else:
        assert chatgpt_proxy.__version__ == "unknown"


def test_version_unknown() -> None:
    x = version_file.read_text()
    try:
        version_file.unlink()
        del sys.modules["chatgpt_proxy._version"]
        chatgpt_proxy._load_version()
        from chatgpt_proxy import __version__
        assert __version__ == "unknown"
    except Exception:
        raise
    finally:
        version_file.write_text(x)
        chatgpt_proxy._load_version()
