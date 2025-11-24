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

"""Read-only models for chatgpt_proxy's 'adhoc ORM'."""

import ast
import datetime
import ipaddress
from dataclasses import dataclass
from enum import StrEnum

max_ast_literal_eval_size = 1000


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

    def as_markdown_dict(self) -> dict:
        return {
            "Message": self.message,
            "Sender:": self.sender_name,
            "Team:": self.sender_team,
            "Channel:": self.channel,
        }

    def wire_format(self) -> str:
        return f"{self.sender_name}\n{self.sender_team}\n{self.channel}\n{self.message}"


@dataclass(slots=True, frozen=True)
class GameObjective:
    name: str
    team_state: Team

    # TODO: this is wrong.
    #   - maybe add custom __str__
    def wire_format(self) -> str:
        return f"('{self.name}',{int(self.team_state)})"


@dataclass(slots=True, frozen=True)
class GameObjectiveState:
    game_id: str
    objectives: list[GameObjective]

    def wire_format(self) -> str:
        # TODO: too many quotes with this method!
        return str([(obj.name, int(obj.team_state)) for obj in self.objectives])

    @staticmethod
    def from_wire_format(
            game_id: str,
            wire_format_data: str,
    ) -> "GameObjectiveState":
        if len(wire_format_data) > max_ast_literal_eval_size:
            raise ValueError("wire_format_data too long")

        raw_objs: list[tuple[str, int]] = ast.literal_eval(wire_format_data)

        t = type(raw_objs)
        if t is not list:
            raise ValueError(f"objs: expected list type, got {t}")

        objs = []
        for obj_name, obj_state in raw_objs:
            if type(obj_name) is not str:
                raise ValueError(f"obj_name: expected str type, got {type(obj_name)}")
            if type(obj_state) is not int:
                raise ValueError(f"obj_state: expected int type, got {type(obj_state)}")

            obj_state_enum = Team(str(obj_state))

            objs.append(GameObjective(
                name=obj_name,
                team_state=obj_state_enum,
            ))

        return GameObjectiveState(
            game_id=game_id,
            objectives=objs,
        )


@dataclass(slots=True, frozen=True)
class GameKill:
    id: int
    game_id: str
    kill_time: datetime.datetime
    killer_name: str
    victim_name: str
    killer_team: Team
    victim_team: Team
    damage_type: str
    kill_distance_m: float

    def as_markdown_dict(self) -> dict:
        # TODO: also do this for other well known damage type prefixes?
        dmg_type = self.damage_type.replace("RODmgType_", "")
        return {
            "Killer": self.killer_name,
            "Victim": self.victim_name,
            "Killer Team:": self.killer_team,
            "Victim Team:": self.victim_team,
            "Damage Type:": dmg_type,
            "Kill Distance (m):": round(self.kill_distance_m, 1),
        }
