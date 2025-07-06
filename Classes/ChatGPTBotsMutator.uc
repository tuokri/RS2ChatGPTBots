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

// TODO: primary features:
//   * Some sort of logic on when to actually send messages to the proxy server.
//   * Which bots do we use to broadcast in game messages? Should we use actual
//     bots or just some sort of proxy actor?
//   * Prefixed chat commands? For example with "!bot bla bla blu blu".

// TODO: do we need to send regular PutGamePlayer messages to keep the proxy-server-side
//       "scoreboard" i.e. player list up to date? E.g., invoke PutGamePlayer for all
//       players in the game every 10 seconds or so?

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
    var PlayerReplicationInfo Sender;
    var string Msg;
    var name Type;
};

struct KeyValuePair_IntInt
{
    var int Key;
    var int Value;
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

// Team index to post the initial greeting message from the LLM with.
var() int InitialGreetingTeamIndex;
// Name to post the initial greeting message from the LLM with.
var() string InitialGreetingName;

// Last known team of a player ID.
// TODO: consider if we need this? We could just send a PUT update on every
//   player spawn, even if their team as not changed. It could however create
//   a lot of unnecessary traffic.
var array<KeyValuePair_IntInt> PlayerIdToTeam;

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

// ---------------------------------------------------------------------------
// PostGameMessage delegates. ------------------------------------------------
// ---------------------------------------------------------------------------

// Send the response from the LLM to in-game chat.
function PostGameMessage_OnComplete(HttpSock Sender)
{
    local int SayTeam;
    local string SayType;
    local string Msg;
    local string SayName;

    `cgbdebug("ReturnData:" @ StringArrayToString(Sender.ReturnData));

    SayType = Sender.ReturnData[0];
    SayTeam = int(Sender.ReturnData[1]);
    SayName = Sender.ReturnData[2];
    Msg = Sender.ReturnData[3];

    CGBProxy.PlayerReplicationInfo.PlayerName = SayName;
    CGBProxy.PlayerReplicationInfo.Team = WorldInfo.Game.GameReplicationInfo.Teams[SayTeam];

    if (SayType == SAY_TEAM)
    {
        WorldInfo.Game.BroadcastTeam(CGBProxy, Msg, 'TeamSay');
    }
    else if (SayType == SAY_ALL)
    {
        WorldInfo.Game.Broadcast(CGBProxy, Msg, 'Say');
    }
    else
    {
        `cgberror("invalid SayType:" @ SayType);
    }

    FinishRequest();
}

function PostGameMessage_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PostGameMessage_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PostGameMessage_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
}

function PostGameMessage_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function PostGameMessage_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

// ---------------------------------------------------------------------------
// PostGameChatMessage delegates. --------------------------------------------
// ---------------------------------------------------------------------------

function PostGameChatMessage_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PostGameChatMessage_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    if (ReturnCode >= 400)
    {
        `cgbwarn("failed with ReturnCode:" @ ReturnCode @ ", message:" @ ReturnMessage);
    }

    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PostGameChatMessage_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PostGameChatMessage_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
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

// ---------------------------------------------------------------------------
// PostGame delegates. -------------------------------------------------------
// ---------------------------------------------------------------------------

function PostGame_OnComplete(HttpSock Sender)
{
    local string Greeting;
    local int Idx;
    local int i;
    local Controller Controller;

    if (Sender.LastStatus == 201)
    {
        GameId = Sender.ReturnData[0];
        `cgblog("received GameId:" @ GameId);

        Greeting = Sender.ReturnData[1]; // TODO: check this is what we want!
        CGBProxy.PlayerReplicationInfo.Team = WorldInfo.Game.GameReplicationInfo.Teams[InitialGreetingTeamIndex];
        CGBProxy.PlayerReplicationInfo.PlayerName = InitialGreetingName;
        WorldInfo.Game.Broadcast(CGBProxy, Greeting, 'Say');
    }

    // This array should be empty when we get here, always, but
    // clear defensively just in case.
    PlayerIdToTeam.Length = 0;
    i = 0;

    // Iterate GRI PriArray, send initial player list, set cached PlayerIdToTeam array.
    for(Idx = 0; Idx < WorldInfo.Game.GameReplicationInfo.PRIArray.Length; ++Idx)
    {
        Controller = Controller(WorldInfo.Game.GameReplicationInfo.PRIArray[Idx].Owner);
        if (Controller != None)
        {
            PutGamePlayer(Controller);
        }
        else
        {
            `cgbwarn("invalid controller for PRI:" @ WorldInfo.Game.GameReplicationInfo.PRIArray[Idx]);
        }

        PlayerIdToTeam[i].Key = WorldInfo.Game.GameReplicationInfo.PRIArray[Idx].PlayerID;
        PlayerIdToTeam[i].Value = WorldInfo.Game.GameReplicationInfo.PRIArray[Idx].Team.TeamIndex;
        ++i;
    }

    FinishRequest();
    FlushGameChatMessageQueue();
}

function PostGame_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage @ StringArrayToString(Sender.ReturnData));

    // TODO: gotta prevent "parallel" retries! Do we get here if any of the other error delegates are fired?
    if (ReturnCode >= 400)
    {
        FinishRequest();
        RetryPostGame();
        return;
    }

    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
}

function PostGame_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
    RetryPostGame();
}

function PostGame_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
    RetryPostGame();
}

function PostGame_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
    RetryPostGame();
}

function PostGame_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

function RetryPostGame(optional int ReturnCode = -1, optional string ReturnMessage)
{
    if (PostGameRetries < MAX_POST_GAME_RETRIES)
    {
        `cgblog(
            "PostGame failed with ReturnCode:"
            @ ReturnCode @ ", message:" @ ReturnMessage
            @ ", retrying, attempt:" @ PostGameRetries
            @ "of" @ MAX_POST_GAME_RETRIES
        );
        ++PostGameRetries;
        PostGame();
    }
    else
    {
        `cgbwarn("max PostGame retries exceeded, features not available for this game!");
        Sock.Destroy();
        Sock = None;
        CGBProxy.Destroy();
        CGBProxy = None;
        RequestQueue.Length = 0;
        GameChatMessageQueue.Length = 0;
        PlayerIdToTeam.Length = 0;
    }
}

// ---------------------------------------------------------------------------
// PutGame delegates. --------------------------------------------------------
// ---------------------------------------------------------------------------

function PutGame_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PutGame_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PutGame_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PutGame_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
}

function PutGame_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function PutGame_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

// ---------------------------------------------------------------------------
// PostGameKill delegates. ---------------------------------------------------
// ---------------------------------------------------------------------------

function PostGameKill_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PostGameKill_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PostGameKill_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PostGameKill_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
}

function PostGameKill_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function PostGameKill_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

// ---------------------------------------------------------------------------
// PutGamePlayer delegates. --------------------------------------------------
// ---------------------------------------------------------------------------

function PutGamePlayer_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PutGamePlayer_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PutGamePlayer_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PutGamePlayer_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
}

function PutGamePlayer_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function PutGamePlayer_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

// ---------------------------------------------------------------------------
// DeleteGamePlayer delegates. -----------------------------------------------
// ---------------------------------------------------------------------------

function DeleteGamePlayer_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function DeleteGamePlayer_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function DeleteGamePlayer_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function DeleteGamePlayer_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
}

function DeleteGamePlayer_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function DeleteGamePlayer_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

// ---------------------------------------------------------------------------
// PutGameObjectiveState delegates. ------------------------------------------
// ---------------------------------------------------------------------------

function PutGameObjectiveState_OnComplete(HttpSock Sender)
{
    FinishRequest();
}

function PutGameObjectiveState_OnReturnCode(HttpSock Sender, int ReturnCode, string ReturnMessage, string HttpVer)
{
    // NOTE: request may still be ongoing after this!
    ClearTimer(NameOf(CancelOpenLink));
    `cgbdebug("HTTP request:" @ ReturnCode @ ReturnMessage);
}

function PutGameObjectiveState_OnResolveFailed(HttpSock Sender, string Hostname)
{
    `cgberror("resolve failed for hostname:" @ Hostname);
    FinishRequest();
}

function PutGameObjectiveState_OnConnectionTimeout(HttpSock Sender)
{
    `cgberror(Sender @ "connection timed out");
    FinishRequest();
}

function PutGameObjectiveState_OnConnectError(HttpSock Sender)
{
    `cgberror(Sender @ "connection failed");
    FinishRequest();
}

function PutGameObjectiveState_OnSendRequestHeaders(HttpSock Sender)
{
    ClearTimer(NameOf(CancelOpenLink));
}

function OverrideBroadcastHandler()
{
    // TODO: can this cause conflict between client and server?
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

// TODO: make sure this receives messages from all teams, squads, etc!
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

    FlushGameChatMessageQueue();
    PostGameChatMessage(Sender, Msg, Type);
}

function FlushGameChatMessageQueue()
{
    local int i;

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
    Sock.AddHeader("Authorization", "Bearer " $ Config.GetApiKey());
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
    Sock.AddHeader("Authorization", "Bearer " $ Config.GetApiKey());
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
    Sock.AddHeader("Authorization", "Bearer " $ Config.GetApiKey());
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
    Sock.AddHeader("Authorization", "Bearer " $ Config.GetApiKey());
    Sock.Delete(Url);
    SetCancelOpenLinkTimer(Timeout);
}

function PostGame()
{
    local Request Req;

    if (GameId != "")
    {
        `cgbwarn("attempted PostGame with GameId already set!");
        return;
    }

    Req.Url = Config.ApiUrl $ "game";
    // TODO: is this the correct port? Or is GameInfo.ListenPort the correct one?
    Req.Data = WorldInfo.GetMapName(True) $ "\n"
        $ GameEngine(class'Engine'.static.GetEngine()).LastURL.Port;
    Req.Verb = Verb_Post;
    Req.OnComplete = PostGame_OnComplete;
    Req.OnReturnCode = PostGame_OnReturnCode;
    Req.OnResolveFailed = PostGame_OnResolveFailed;
    Req.OnConnectionTimeout = PostGame_OnConnectionTimeout;
    Req.OnConnectError = PostGame_OnConnectError;
    Req.OnSendRequestHeaders = PostGame_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function PutGame()
{
    local string PutData;
    local Request Req;

    // Game end time.
    PutData = string(WorldInfo.RealTimeSeconds);

    Req.Url = Config.ApiUrl $ "game";
    Req.Data = PutData;
    Req.Verb = Verb_Put;
    Req.OnComplete = PutGame_OnComplete;
    Req.OnReturnCode = PutGame_OnReturnCode;
    Req.OnResolveFailed = PutGame_OnResolveFailed;
    Req.OnConnectionTimeout = PutGame_OnConnectionTimeout;
    Req.OnConnectError = PutGame_OnConnectError;
    Req.OnSendRequestHeaders = PutGame_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

// Requests an LLM response from the server, taking current game state
// into account, in addition to the provided prompt.
function PostGameMessage(name SayType, int SayTeamIndex, string SayName, string Prompt)
{
    local Request Req;
    local string MsgType;

    if (GameId == "")
    {
        `cgbwarn("attempted to post game message without GameId");
        return;
    }

    if (SayType == 'Say')
    {
        MsgType = SAY_ALL;
    }
    else if (SayType == 'TeamSay')
    {
        MsgType = SAY_TEAM;
    }
    else
    {
        `cgberror("unexpected SayType:" @ SayType);
    }

    Req.Url = Config.ApiUrl $ "game/" $ GameId $ "/message";
    Req.Data = MsgType $ "\n" $ SayTeamIndex $ "\n" $ SayName $ "\n" $ Prompt;
    Req.Verb = Verb_Post;
    Req.OnComplete = PostGameMessage_OnComplete;
    Req.OnReturnCode = PostGameMessage_OnReturnCode;
    Req.OnResolveFailed = PostGameMessage_OnResolveFailed;
    Req.OnConnectionTimeout = PostGameMessage_OnConnectionTimeout;
    Req.OnConnectError = PostGameMessage_OnConnectError;
    Req.OnSendRequestHeaders = PostGameMessage_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

// TODO: should we send these in batches?
function PostGameChatMessage(PlayerReplicationInfo Sender, string Msg, name Type)
{
    local Request Req;
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
        `cgberror("unexpected Type:" @ Type);
    }

    Req.Url = Config.ApiUrl $ "game/" $ GameId $ "/chat_message";
    Req.Data = Sender.PlayerName $ "\n" $ Sender.Team.TeamIndex $ "\n" $ MsgType $ "\n" $ Msg;
    Req.Verb = Verb_Post;
    Req.OnComplete = PostGameChatMessage_OnComplete;
    Req.OnReturnCode = PostGameChatMessage_OnReturnCode;
    Req.OnResolveFailed = PostGameChatMessage_OnResolveFailed;
    Req.OnConnectionTimeout = PostGameChatMessage_OnConnectionTimeout;
    Req.OnConnectError = PostGameChatMessage_OnConnectError;
    Req.OnSendRequestHeaders = PostGameChatMessage_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function DeleteGamePlayer(int PlayerID)
{
    local Request Req;

    if (GameId == "")
    {
        `cgbwarn("attempted to delete game player without GameId");
        return;
    }

    Req.Url = Config.ApiUrl $ "game/" $ GameId $ "/player/" $ PlayerID;
    Req.Verb = Verb_Delete;
    Req.OnComplete = DeleteGamePlayer_OnComplete;
    Req.OnReturnCode = DeleteGamePlayer_OnReturnCode;
    Req.OnResolveFailed = DeleteGamePlayer_OnResolveFailed;
    Req.OnConnectionTimeout = DeleteGamePlayer_OnConnectionTimeout;
    Req.OnConnectError = DeleteGamePlayer_OnConnectError;
    Req.OnSendRequestHeaders = DeleteGamePlayer_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function PutGamePlayer(Controller Player)
{
    local Request Req;

    if (GameId == "")
    {
        `cgbwarn("attempted to put game player without GameId");
        return;
    }

    if (Player.PlayerReplicationInfo == None)
    {
        `cgbwarn("attempted to put game player with null PlayerReplicationInfo");
        return;
    }

    Req.Url = Config.ApiUrl $ "game/" $ GameId $ "/player/" $ Player.PlayerReplicationInfo.PlayerID;
    Req.Data = Player.PlayerReplicationInfo.PlayerName $ "\n"
        $ Player.PlayerReplicationInfo.Team.TeamIndex $ "\n"
        $ Player.PlayerReplicationInfo.Score;
    Req.Verb = Verb_Post;
    Req.OnComplete = PutGamePlayer_OnComplete;
    Req.OnReturnCode = PutGamePlayer_OnReturnCode;
    Req.OnResolveFailed = PutGamePlayer_OnResolveFailed;
    Req.OnConnectionTimeout = PutGamePlayer_OnConnectionTimeout;
    Req.OnConnectError = PutGamePlayer_OnConnectError;
    Req.OnSendRequestHeaders = PutGamePlayer_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function PostGameKill(Controller Killer, Controller Victim)
{
    local Request Req;
    local ROPawn VictimPawn;

    if (GameId == "")
    {
        `cgbwarn("attempted to post game kill without GameId");
        return;
    }

    VictimPawn = ROPawn(Victim.Pawn);

    Req.Url = Config.ApiUrl $ "game/" $ GameId $ "/kill";

    Req.Data = WorldInfo.RealTimeSeconds $ "\n"
        $ Killer.PlayerReplicationInfo.PlayerName $ "\n"
        $ Victim.PlayerReplicationInfo.PlayerName $ "\n"
        $ Killer.PlayerReplicationInfo.Team.TeamIndex $ "\n"
        $ Victim.PlayerReplicationInfo.Team.TeamIndex;

    if (VictimPawn != None)
    {
        Req.Data $= VictimPawn.LastTakeHitInfo.DamageType $ "\n"
            $ VSize(VictimPawn.LastTakeHitInfo.HitLocation - Killer.Pawn.Location) / 50.0;
    }
    else
    {
        `cgbwarn("VictimPawn is None, using default values for damage type and hit location");
        Req.Data $= "None" $ "\n" $ "-1";
    }

    Req.Verb = Verb_Post;
    Req.OnComplete = PostGameKill_OnComplete;
    Req.OnReturnCode = PostGameKill_OnReturnCode;
    Req.OnResolveFailed = PostGameKill_OnResolveFailed;
    Req.OnConnectionTimeout = PostGameKill_OnConnectionTimeout;
    Req.OnConnectError = PostGameKill_OnConnectError;
    Req.OnSendRequestHeaders = PostGameKill_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function PutGameObjectiveState()
{
    local Request Req;
    local string PutData;
    local int i;
    local ROGameReplicationInfo ROGRI;

    if (GameId == "")
    {
        `cgbwarn("attempted to put game objective state without GameId");
        return;
    }

    ROGRI = ROGameReplicationInfo(WorldInfo.Game.GameReplicationInfo);
    if (ROGRI == None)
    {
        `cgbwarn("unable to get ROGameReplicationInfo");
        return;
    }

    PutData = "[";
    for (i = 0; i < ROGRI.Objectives.Length; ++i)
    {
        PutData $= "(" $ ROGRI.Objectives[i].ObjName $ "," $ int(ROGRI.Objectives[i].ObjState) $ ")";

        if (i < ROGRI.Objectives.Length - 1)
        {
            PutData $= ",";
        }
    }
    PutData $= "]";

    Req.Url = Config.ApiUrl $ "game/" $ GameId $ "/objective_state";
    Req.Data = PutData;
    Req.Verb = Verb_Put;
    Req.OnComplete = PutGameObjectiveState_OnComplete;
    Req.OnReturnCode = PutGameObjectiveState_OnReturnCode;
    Req.OnResolveFailed = PutGameObjectiveState_OnResolveFailed;
    Req.OnConnectionTimeout = PutGameObjectiveState_OnConnectionTimeout;
    Req.OnConnectError = PutGameObjectiveState_OnConnectError;
    Req.OnSendRequestHeaders = PutGameObjectiveState_OnSendRequestHeaders;

    RequestQueue.AddItem(Req);
    if (!IsTimerActive(NameOf(ProcessRequestQueue)))
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function ProcessRequestQueue()
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
    Sock.OnSendRequestHeaders = RequestQueue[0].OnSendRequestHeaders;

    RequestQueue.Remove(0, 1);
    if (RequestQueue.Length > 0)
    {
        SetTimer(0.001, False, NameOf(ProcessRequestQueue));
    }
}

function SetCancelOpenLinkTimer(optional float Timeout = 2.0)
{
    SetTimer(Timeout, False, NameOf(CancelOpenLink));
}

// Stupid hack to avoid HttpSock from spamming logs if connection fails!
function CancelOpenLink()
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
    local int Idx;

    if (GameId != "" && Exiting.PlayerReplicationInfo != None)
    {
        DeleteGamePlayer(Exiting.PlayerReplicationInfo.PlayerID);

        Idx = PlayerIdToTeam.Find('Key', Exiting.PlayerReplicationInfo.PlayerID);
        if (Idx != INDEX_NONE)
        {
            PlayerIdToTeam.Remove(Idx, 1);
        }
    }

    super.NotifyLogout(Exiting);
}

function NotifyLogin(Controller NewPlayer)
{
    local int Idx;
    local KeyValuePair_IntInt KV;

    if (GameId != "")
    {
        PutGamePlayer(NewPlayer);

        Idx = PlayerIdToTeam.Find('Key', NewPlayer.PlayerReplicationInfo.PlayerID);
        if (Idx == INDEX_NONE)
        {
            KV.Key = NewPlayer.PlayerReplicationInfo.PlayerID;
            KV.Value = NewPlayer.PlayerReplicationInfo.Team.TeamIndex;
            PlayerIdToTeam.AddItem(KV);
            `cgbdebug("added new player ID to team mapping:"
                @ NewPlayer.PlayerReplicationInfo.PlayerID @ "->"
                @ NewPlayer.PlayerReplicationInfo.Team.TeamIndex
            );
        }
    }

    super.NotifyLogin(NewPlayer);
}

function ScoreKill(Controller Killer, Controller Victim)
{
    // Just ignore kills until we have the ID.
    if (GameId != "")
    {
        PostGameKill(Killer, Victim);
    }

    super.ScoreKill(Killer, Victim);
}

function NavigationPoint FindPlayerStart(
    Controller Player,
    optional byte InTeam,
    optional string IncomingName)
{
    local int Idx;
    local KeyValuePair_IntInt KV;

    if (GameId != "")
    {
        // If a player ID's team has changed, we have to send a PUT update.
        Idx = PlayerIdToTeam.Find('Key', Player.PlayerReplicationInfo.PlayerID);
        if (Idx == INDEX_NONE)
        {
            KV.Key = Player.PlayerReplicationInfo.PlayerID;
            KV.Value = Player.PlayerReplicationInfo.Team.TeamIndex;
            PlayerIdToTeam.AddItem(KV);
            `cgbdebug("added new player ID to team mapping:"
                @ Player.PlayerReplicationInfo.PlayerID @ "->"
                @ Player.PlayerReplicationInfo.Team.TeamIndex
            );
        }
        else
        {
            // Player exists, send update to backend if team changed.
            // There's no good way to capture team change events, so this is
            // the best effort, close enough approach.
            if (PlayerIdToTeam[Idx].Value != Player.PlayerReplicationInfo.Team.TeamIndex)
            {
                PlayerIdToTeam[Idx].Value = Player.PlayerReplicationInfo.Team.TeamIndex;
                PutGamePlayer(Player);
                `cgbdebug("updated player ID to team mapping:"
                    @ Player.PlayerReplicationInfo.PlayerID @ "->"
                    @ Player.PlayerReplicationInfo.Team.TeamIndex
                );
            }
        }
    }

    return Super.FindPlayerStart(Player, InTeam, IncomingName);
}

function string StringArrayToString(array<string> Strings)
{
    local int i;
    local string Result;

    Result = "[";
    for (i = 0; i < Strings.Length; ++i)
    {
        Result $= Strings[i];
        if (i < (Strings.Length - 1))
        {
            Result $= ",";
        }
    }
    Result $= "]";

    return Result;
}

DefaultProperties
{
    InitialGreetingTeamIndex=`NEUTRAL_TEAM_INDEX
    InitialGreetingName="MAINFRAME CHARLIE"
}
