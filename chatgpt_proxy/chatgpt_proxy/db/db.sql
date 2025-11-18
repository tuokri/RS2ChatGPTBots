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

CREATE EXTENSION IF NOT EXISTS "timescaledb";

-- TODO: enforce only a single token per game_server_address:game_server_port is allowed!
CREATE TABLE IF NOT EXISTS "game_server_api_key"
(
    created_at          TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    api_key_hash        BYTEA       NOT NULL,
    game_server_address INET        NOT NULL,
    game_server_port    INTEGER     NOT NULL,
    name                TEXT
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
-- Intentionally not tied to player ID, since the "game_player" table
-- represents the latest known game state (scoreboard), NOT all current
-- and past players of the game session.
-- TODO: should this be a hypertable?
CREATE TABLE IF NOT EXISTS "game_chat_message"
(
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message     TEXT        NOT NULL,
    game_id     TEXT        NOT NULL,
    send_time   TIMESTAMPTZ NOT NULL,
    sender_name TEXT,
    sender_team INT,
    channel     INT,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

-- Kills scored during a game session. Similar to "game_chat_message",
-- this is not tied to specific player IDs on purpose.
-- TODO: should this be a hypertable?
CREATE TABLE IF NOT EXISTS "game_kill"
(
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT        NOT NULL,
    kill_time       TIMESTAMPTZ NOT NULL,
    killer_name     TEXT,
    victim_name     TEXT,
    killer_team     INTEGER,
    victim_team     INTEGER,
    damage_type     TEXT,
    kill_distance_m DOUBLE PRECISION,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

-- Represents the current state of an ongoing game, essentially
-- reflects the in-game scoreboard (minus some columns) at a given time.
CREATE TABLE IF NOT EXISTS "game_player"
(
    game_id TEXT    NOT NULL,
    id      INTEGER NOT NULL UNIQUE,
    name    TEXT    NOT NULL,
    team    INTEGER NOT NULL,
    score   INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "game_objective_state"
(
    game_id    TEXT     NOT NULL UNIQUE,
    objectives TEXT[][] NOT NULL,

    FOREIGN KEY (game_id) REFERENCES game (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "query_statistics"
(
    id                    BOOLEAN PRIMARY KEY UNIQUE DEFAULT TRUE,
    steam_web_api_queries BIGINT NOT NULL            DEFAULT 0,

    CHECK (id)
);
INSERT INTO query_statistics DEFAULT
VALUES
ON CONFLICT DO NOTHING;

-- Query history and statistics to OpenAI API.
CREATE TABLE IF NOT EXISTS "openai_query"
(
    time                TIMESTAMPTZ NOT NULL,
    game_id             TEXT        NOT NULL,
    game_server_address INET        NOT NULL,
    game_server_port    INTEGER     NOT NULL,
    request_length      INTEGER     NOT NULL,
    response_length     INTEGER     NOT NULL,
    openai_response_id  TEXT        NOT NULL,

    FOREIGN KEY (game_id) REFERENCES game (id)
);

CREATE INDEX ON "openai_query" (game_id, time DESC);
CREATE INDEX ON "openai_query" (game_server_address, game_server_port, time DESC);

SELECT create_hypertable('openai_query', 'time');
SELECT add_retention_policy('openai_query', INTERVAL '1 months');

ALTER TABLE "openai_query"
    SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'game_server_address, game_server_port'
        );

SELECT add_compression_policy('openai_query', INTERVAL '2 days');
