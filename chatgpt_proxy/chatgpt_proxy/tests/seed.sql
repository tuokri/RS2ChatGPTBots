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

INSERT INTO "game" (id, level, start_time, stop_time, game_server_address, game_server_port,
                    openai_previous_response_id)
VALUES ('first_game', 'VNTE-Resort', NOW(), NULL,
        INET '127.0.0.1', 7777, NULL);

INSERT INTO "game" (id, level, start_time, stop_time, game_server_address, game_server_port,
                    openai_previous_response_id)
VALUES ('old_game_1', 'VNTE-CuChi', NOW() - INTERVAL '1 hour', NOW(),
        INET '127.0.1.1', 7777, 'dummy_id_here');

INSERT INTO "game" (id, level, start_time, stop_time, game_server_address, game_server_port,
                    openai_previous_response_id)
VALUES ('old_game_555', 'VNTE-WTF', NOW() - INTERVAL '12 hours', NOW() - INTERVAL '11 hours',
        INET '127.0.1.1', 7777, 'dummy_id_here');

INSERT INTO "game" (id, level, start_time, stop_time, game_server_address, game_server_port,
                    openai_previous_response_id)
VALUES ('game_from_forbidden_server', 'VNTE-FORBIDDEN', NOW(), NULL,
        INET '88.99.12.1', 6969, NULL);
