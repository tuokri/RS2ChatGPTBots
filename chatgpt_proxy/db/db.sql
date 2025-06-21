-- MIT License
--
-- Copyright (c) 2025 Tuomo Kriikkula
--
-- Permission is hereby granted, free of charge, to any person obtaining a copy
-- of this software and associated documentation files (the "Software"), to deal
-- in the Software without restriction, including without limitation the rights
-- to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
-- copies of the Software, and to permit persons to whom the Software is
-- furnished to do so, subject to the following conditions:
--
-- The above copyright notice and this permission notice shall be included in all
-- copies or substantial portions of the Software.
--
-- THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
-- IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
-- FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
-- AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
-- LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
-- OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
-- SOFTWARE.

CREATE TABLE IF NOT EXISTS "game_server_api_key"
(
    created_at          TIMESTAMPTZ NOT NULL,
    api_key_hash        TEXT        NOT NULL, -- TODO: this design needs some thought.
    game_server_address INET        NOT NULL,
    game_server_port    INTEGER     NOT NULL
);

-- Server game session. A new one begins on map change.
CREATE TABLE IF NOT EXISTS "game"
(
    id                          TEXT PRIMARY KEY,
    level                       TEXT        NOT NULL,
    start_time                  TIMESTAMPTZ NOT NULL,
    stop_time                   TIMESTAMPTZ,
    game_server_address         INET        NOT NULL,
    game_server_port            INTEGER     NOT NULL,
    openai_previous_response_id TEXT
);

-- Chat messages belonging to a specific game session sent by players.
CREATE TABLE IF NOT EXISTS "game_chat_message"
(
    game_id     TEXT        NOT NULL,
    send_time   TIMESTAMPTZ NOT NULL,
    sender_name TEXT,
    sender_team TEXT,
    channel     TEXT,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

-- Kills scored during a game session.
CREATE TABLE IF NOT EXISTS "game_kill"
(
    game_id         TEXT        NOT NULL,
    kill_time       TIMESTAMPTZ NOT NULL,
    killer_name     TEXT,
    victim_name     TEXT,
    killer_team     TEXT,
    victim_team     TEXT,
    damage_type     TEXT,
    kill_distance_m DOUBLE PRECISION,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

-- Represents the current state of an ongoing game, essentially
-- reflects the in-game scoreboard (minus some columns) at a given time.
CREATE TABLE IF NOT EXISTS "game_player"
(
    game_id TEXT    NOT NULL,
    id      INTEGER NOT NULL,
    name    TEXT    NOT NULL,
    score   INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

-- Query history and statistics to OpenAI API.
CREATE TABLE IF NOT EXISTS "openai_query"
(
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    time                TIMESTAMPTZ NOT NULL,
    game_server_address INET        NOT NULL,
    game_server_port    INTEGER     NOT NULL,
    request_length      INTEGER     NOT NULL,
    response_length     INTEGER
);
