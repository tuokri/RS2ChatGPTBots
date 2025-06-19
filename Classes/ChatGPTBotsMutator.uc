/*
 * Copyright (c) 2025 Tuomo Kriikkula
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

class ChatGPTBotsMutator extends ROMutator
    config(Mutator_ChatGPTBots)
    dependson(HttpSock);

// TODO: add way to hook into in game chat messages.
//   * Some sort of logic on when to actually send messages to the proxy server.
//   * Which bots do we use to broadcast in game messages? Should we use actual
//     bots or just some sort of proxy actor?
//   * Prefixed chat commands? For example with "!bot bla bla blu blu".

var HttpSock Sock;
var CGBMutatorConfig Config;

function CreateHTTPClient()
{
    Sock = Spawn(class'HttpSock', self);
    if (Sock == None)
    {
        `cgberror("failed to spawn HttpSock!");
        return;
    }
}

function CreateConfig()
{
    Config = new class'CGBMutatorConfig';
    if (Config == None)
    {
        `cgberror("failed to initialize config!");
        return;
    }
    Config.ValidateConfig();
}

event PreBeginPlay()
{
    super.PreBeginPlay();

    CreateHTTPClient();
    CreateConfig();

    `cgblog("mutator initialized");
}

function HTTPGet(string Url, optional float Deadline = 2.0)
{
    if (Sock == None)
    {
        return;
    }

    `cgblog("sending HTTP GET request to: " $ Url);
    Sock.Get(Url);
    SetCancelOpenLinkTimer(Deadline);
}

function HTTPPost(string Url, optional float Deadline = 2.0)
{
    if (Sock == None)
    {
        return;
    }

    `cgblog("sending HTTP POST request to: " $ Url);
    Sock.Post(Url);
    SetCancelOpenLinkTimer(Deadline);
}

final function SetCancelOpenLinkTimer(optional float Deadline = 2.0)
{
    SetTimer(Deadline, False, NameOf(CancelOpenLink));
}

// Stupid hack to avoid HttpSock from spamming logs if connection fails!
final function CancelOpenLink()
{
    if (Sock != None)
    {
        `cgblog("cancelling HttpSock connection attempt");
        Sock.Abort();
    }
}

function NotifyLogout(Controller Exiting)
{
    super.NotifyLogout(Exiting);
}

function NotifyLogin(Controller NewPlayer)
{
    super.NotifyLogin(NewPlayer);
}

function ScoreKill(Controller Killer, Controller Victim)
{
    super.ScoreKill(Killer, Victim);
}
