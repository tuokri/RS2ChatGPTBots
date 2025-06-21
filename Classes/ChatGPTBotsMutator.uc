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

// TODO: prevent making parallel requests! HttpSock can only handle one at a time.

// TODO: add way to hook into in game chat messages.
//   * Some sort of logic on when to actually send messages to the proxy server.
//   * Which bots do we use to broadcast in game messages? Should we use actual
//     bots or just some sort of proxy actor?
//   * Prefixed chat commands? For example with "!bot bla bla blu blu".

// TODO: give the LLM a max message length. Check what is best suitable.
const MAX_MESSAGE_LENGTH = 260;

// TODO: add other verbs if needed.
enum EHTTPVerb
{
    Verb_Get,
    Verb_Post,
};

struct Request
{
    var EHTTPVerb Verb;
    var string Url;
    var string Data;
    var delegate<HttpSock.OnComplete> OnComplete;
    var delegate<HttpSock.OnReturnCode> OnReturnCode;
    var delegate<HttpSock.OnResolveFailed> OnResolveFailed;
    var delegate<HttpSock.OnConnectionTimeout> OnConnectionTimeout;
    var delegate<HttpSock.OnConnectError> OnConnectError;
};

var CGBProxy CGBProxy;
var HttpSock Sock;
var CGBMutatorConfig Config;
var array<Request> RequestQueue;
var bool bRequestOngoing;

var string GameId;

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

function FinishRequest()
{
    bRequestOngoing = False;
    ClearTimer(NameOf(CancelOpenLink));
}

function PostGameChatMessage_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PostGameChatMessage_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
}

function PostGameChatMessage_OnResolveFailed(HttpSock Sender, string Hostname)
{
    FinishRequest();
}

function PostGameChatMessage_OnConnectionTimeout(HttpSock Sender)
{
    FinishRequest();
}

function PostGameChatMessage_OnConnectError(HttpSock Sender)
{
    FinishRequest();
}

function OverrideBroadcastHandler()
{
    // TODO: can this cause conflict with client and server?
    if (WorldInfo.NetMode != NM_DedicatedServer)
    {
        return;
    }

    if (WorldInfo.Game.BroadcastHandler.Class != class'ROBroadcastHandler')
    {
        `cgbwarn("BroadcastHandler class is unexpected:"
            @ WorldInfo.Game.BroadcastHandler.Class
            $ ", already overridden by another mod?"
        );
    }

    WorldInfo.Game.BroadcastHandler = Spawn(class'CGBBroadCastHandler', WorldInfo.Game);
}

function ReceiveMessage(PlayerReplicationInfo Sender, string Msg, name Type)
{
    PostGameChatMessage(Sender, Msg, Type);
}

event PreBeginPlay()
{
    super.PreBeginPlay();

    CreateHTTPClient();
    CreateConfig();
    OverrideBroadcastHandler();

    `cgblog("mutator initialized");
}

event PostBeginPlay()
{
    super.PostBeginPlay();

    CGBProxy = Spawn(class'CGBProxy');
    CGBProxy.AddReceiver(ReceiveMessage);
}

function HTTPGet(string Url, optional float Timeout = 2.0)
{
    if (Sock == None)
    {
        return;
    }

    `cgblog("sending HTTP GET request to: " $ Url);
    Sock.Get(Url);
    SetCancelOpenLinkTimer(Timeout);
}

function HTTPPost(string Url, optional string PostData, optional float Timeout = 2.0)
{
    if (Sock == None)
    {
        return;
    }

    `cgblog("sending HTTP POST request to: " $ Url);
    Sock.Post(Url, PostData);
    SetCancelOpenLinkTimer(Timeout);
}

function PostGame(/* TODO: game data arguments here! */)
{
    local string PostData;

    // TODO: queue request here.

    // HTTPPost(Config.ApiUrl $ "game", PostData);
}

// Requests an LLM response from the server, taking current game state
// into account, in addition to the provided prompt.
function PostGameMessage(string Prompt)
{
    local string PostData;

    if (GameId == "")
    {
        `cgbwarn("attempted to post game message without GameId");
        return;
    }

    // TODO: queue request here.

    // HTTPPost(Config.ApiUrl $ "game/" $ GameId $ "/message", PostData);
}

// TODO: should we send these in batches?
function PostGameChatMessage(PlayerReplicationInfo Sender, string Msg, name Type)
{
    local Request Request;
    local string PostData;

    if (GameId == "")
    {
        `cgbwarn("attempted to post game chat message without GameId");
        return;
    }

    // TODO: build request here, put it in queue.
    // TODO: if queue processing timer is active, no need to set it,
    //       else set it. It will set the timer again, itself, if
    //       there are more requests to process.

    Request.Url = Config.ApiUrl $ "game/" $ GameId $ "/chat_message";
    Request.Data = Msg; // TODO: make proper newline-separated data.
    Request.Verb = Verb_Post;
    Request.OnComplete = PostGameChatMessage_OnComplete;
    Request.OnReturnCode = PostGameChatMessage_OnReturnCode;
    Request.OnResolveFailed = PostGameChatMessage_OnResolveFailed;
    Request.OnConnectionTimeout = PostGameChatMessage_OnConnectionTimeout;
    Request.OnConnectError = PostGameChatMessage_OnConnectError;

    RequestQueue.AddItem(Request);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

final function ProcessRequestQueue()
{
    // TODO: if we want parallel request capability we need to spawn
    //       and destroy sockets dynamically for each request.
    if (bRequestOngoing)
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }

    switch (RequestQueue[0].Verb)
    {
        case Verb_Get:
            HTTPGet(RequestQueue[0].Url);
            break;
        case Verb_Post:
            HTTPPost(
                RequestQueue[0].Url,
                RequestQueue[0].Data,
            );
            break;
        default:
            `cgberror("invalid HTTPVerb:" @ RequestQueue[0].Verb);
            break;
    }

    bRequestOngoing = True;
    Sock.OnComplete = RequestQueue[0].OnComplete;
    Sock.OnReturnCode = RequestQueue[0].OnReturnCode;
    Sock.OnResolveFailed = RequestQueue[0].OnResolveFailed;
    Sock.OnConnectionTimeout = RequestQueue[0].OnConnectionTimeout;
    Sock.OnConnectError = RequestQueue[0].OnConnectError;

    RequestQueue.Remove(0, 1);
    if (RequestQueue.Length > 0)
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

final function SetCancelOpenLinkTimer(optional float Timeout = 2.0)
{
    SetTimer(Timeout, False, NameOf(CancelOpenLink));
}

// Stupid hack to avoid HttpSock from spamming logs if connection fails!
final function CancelOpenLink()
{
    if (Sock != None)
    {
        `cgblog("cancelling HttpSock connection attempt");
        Sock.Abort();
        Sock.OnComplete = None;
        Sock.OnReturnCode = None;
        Sock.OnResolveFailed = None;
        Sock.OnConnectionTimeout = None;
        Sock.OnConnectError = None;
    }
    bRequestOngoing = False;
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

DefaultProperties
{
}
