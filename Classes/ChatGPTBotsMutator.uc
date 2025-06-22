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

// TODO: make generic versions of HttpSock delegates that are duplicated for
//       all requests!

// TODO: give the LLM a max message length. Check what is best suitable.
const MAX_MESSAGE_LENGTH = 260;

const SAY_ALL = "0";
const SAY_TEAM = "1";

// TODO: add other verbs if needed.
enum EHTTPVerb
{
    Verb_Get,
    Verb_Post,
    Verb_Put,
    Verb_Delete
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
    var delegate<HttpSock.OnSendRequestHeaders> OnSendRequestHeaders;
};

struct GameChatMessage
{
    var PlayerController Sender;
    var string Msg;
    var name Type;
};

var CGBProxy CGBProxy;
var HttpSock Sock;
var CGBMutatorConfig Config;
var array<Request> RequestQueue;
var array<GameChatMessage> GameChatMessageQueue;
var bool bRequestOngoing;
var bool bInitialPlayersSent;
var int PostGameRetries; // TODO: implement retry mechanism.
const MAX_POST_GAME_RETRIES = 5;
const POST_GAME_RETRY_DELAY = 5.0;

var float FirstCheckTime;
const MAX_GAME_WAIT_TIME = 30.0;

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

// Send the response from the LLM to in-game chat.
function PostGameMessage_OnComplete(HttpSock Sender)
{
    local string SayType;
    local string Msg;

    `cgbdebug("ReturnData:" @ Sender.ReturnData);

    // TODO: parse SayType\nMessage

    // TODO: is this the best way to send messages here?
    if (SayType == SAY_TEAM)
    {
        CGBProxy.ServerTeamSay("TODO: message here!");
    }
    else if (SayType == SAY_ALL)
    {
        CGBProxy.ServerSay("TODO: what the dog?");
    }
    else
    {
        `cgberror("invalid SayType:" @ SayType);
    }

    FinishRequest();
}

function PostGameChatMessage_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PostGameChatMessage_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PostGameChatMessage_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cbgerror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PostGameChatMessage_OnConnectionTimeout(HttpSock Sender)
{
    `cbgerror(Sender @ "connection timed out");
    FinishRequest();
}

function PostGameChatMessage_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function PostGameChatMessage_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
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
    local int i;

    // Receiving GameId from the proxy server will be delayed.
    if (GameId == "")
    {
        i = GameChatMessageQueue.Length;
        GameChatMessageQueue.Add(1);
        GameChatMessageQueue[i].Sender = Sender;
        GameChatMessageQueue[i].Msg = Msg;
        GameChatMessageQueue[i].Type = Type;
        return;
    }

    if (GameChatMessageQueue.Length > 0)
    {
        for (i = 0; i < GameChatMessageQueue.Length; ++i)
        {
            PostGameChatMessage(
                GameChatMessageQueue[i].Sender,
                GameChatMessageQueue[i].Msg,
                GameChatMessageQueue[i].Type);
        }

        GameChatMessageQueue.Length = 0;
    }

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

    FirstCheckTime = WorldInfo.RealTimeSeconds;
    SetTimer(1.0, False, NameOf(CheckGameIsGoodToGo));
}

// Delayed check to let all the players load in.
function CheckGameIsGoodToGo()
{
    local bool bGood;

    if (
        (WorldInfo.RealTimeSeconds >= FirstCheckTime + MAX_GAME_WAIT_TIME)
        || (WorldInfo.Game.NumPlayers >= WorldInfo.Game.MaxPlayers)
    )
    {
        bGood = True;
    }

    if (bGood)
    {
        PostGame();
    }
    else
    {
        SetTimer(1.0, False, NameOf(CheckGameIsGoodToGo));
    }
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

function HTTPPut(string Url, optional string PutData, optional float Timeout = 2.0)
{
    if (Sock == None)
    {
        return;
    }

    `cgblog("sending HTTP PUT request to: " $ Url);
    Sock.Put(Url, PutData);
    SetCancelOpenLinkTimer(Timeout);
}

function HTTPDelete(string Url, optional float Timeout = 2.0)
{
    if (Sock == None)
    {
        return;
    }

    `cgblog("sending HTTP DELETE request to: " $ Url);
    Sock.Delete(Url);
    SetCancelOpenLinkTimer(Timeout);
}

function PostGame(/* TODO: game data arguments here! */)
{
    local string PostData;

    // TODO: NEED TO RETRY THIS IF IT FAILS FOR WHATEVER REASON!

    // TODO: queue request here.

    // TODO: in the OnCompleted handler of PostGame, we need to send
    //       the initial list of players and set bInitialPlayersSent = True!

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
    local string MsgType;

    if (GameId == "")
    {
        `cgbwarn("attempted to post game chat message without GameId");
        return;
    }

    if (Type == 'Say')
    {
        MsgType = SAY_ALL;
    }
    else if (Type == 'TeamSay')
    {
        MsgType = SAY_TEAM;
    }
    else
    {
        `cbgerror("unexpected Type:" @ Type);
    }

    Request.Url = Config.ApiUrl $ "game/" $ GameId $ "/chat_message";
    Request.Data = Sender.PlayerID $ "\n" $ MsgType $ "\n" $ Msg;
    Request.Verb = Verb_Post;
    Request.OnComplete = PostGameChatMessage_OnComplete;
    Request.OnReturnCode = PostGameChatMessage_OnReturnCode;
    Request.OnResolveFailed = PostGameChatMessage_OnResolveFailed;
    Request.OnConnectionTimeout = PostGameChatMessage_OnConnectionTimeout;
    Request.OnConnectError = PostGameChatMessage_OnConnectError;
    Request.OnSendRequestHeaders = PostGameChatMessage_OnSendRequestHeaders;

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
            HTTPPost(RequestQueue[0].Url, RequestQueue[0].Data);
            break;
        case Verb_Put:
            HTTPPut(RequestQueue[0].Url, RequestQueue[0].Data);
            break;
        case Verb_Delete:
            HTTPDelete(RequestQueue[0].Url);
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
        Sock.OnSendRequestHeaders = None;
    }
    bRequestOngoing = False;
}

function NotifyLogout(Controller Exiting)
{
    if (GameId != "" && Exiting.PlayerReplicationInfo != None)
    {
        // DeleteGamePlayer();
    }

    super.NotifyLogout(Exiting);
}

function NotifyLogin(Controller NewPlayer)
{
    if (GameId != "")
    {
        // PutGamePlayer();
    }

    super.NotifyLogin(NewPlayer);
}

function ScoreKill(Controller Killer, Controller Victim)
{
    if (GameId == "")
    {
        // TODO: queue these.
    }
    else
    {
        // PostGameKill();
    }

    super.ScoreKill(Killer, Victim);
}

DefaultProperties
{
}
