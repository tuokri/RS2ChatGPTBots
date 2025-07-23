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

"""Read-only models for chatgpt_proxy's 'ad-hoc ORM'."""

import datetime
import ipaddress
from dataclasses import dataclass
from enum import StrEnum


# Mirrored in ChatGPTBotsMutator.uc!
class SayType(StrEnum):
    ALL = "0"
    TEAM = "1"


class Team(StrEnum):
    North = "0"
    South = "1"
    Neutral = "3"


@dataclass(slots=True, frozen=True)
class Game:
    id: str
    level: str
    start_time: datetime.datetime
    game_server_address: ipaddress.IPv4Address
    game_server_port: int
    stop_time: datetime.datetime | None = None
    openai_previous_response_id: str | None = None


@dataclass(slots=True, frozen=True)
class GamePlayer:
    game_id: str
    id: int
    name: str
    team: Team
    score: int

    def wire_format(self) -> str:
        return f"{self.name}\n{self.team}\n{self.score}"


@dataclass(slots=True, frozen=True)
class OpenAIQuery:
    time: datetime.datetime
    game_id: str
    game_server_address: ipaddress.IPv4Address
    game_server_port: int
    request_length: int
    response_length: int
    openai_response_id: str


@dataclass(slots=True, frozen=True)
class GameChatMessage:
    id: int
    message: str
    game_id: str
    send_time: datetime.datetime
    sender_name: str
    sender_team: Team
    channel: SayType

    def wire_format(self) -> str:
        return f"{self.sender_name}\n{self.sender_team}\n{self.channel}\n{self.message}"


@dataclass(slots=True, frozen=True)
class GameObjective:
    name: str
    team_state: Team


@dataclass(slots=True, frozen=True)
class GameObjectiveState:
    game_id: str
    objectives: list[GameObjective]

    def wire_format(self) -> str:
        raise NotImplementedError

    @staticmethod
    def from_wire_format(self, data: str) -> "GameObjectiveState":
        raise NotImplementedError
