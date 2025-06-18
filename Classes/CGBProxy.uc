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

// Custom proxy for capturing chat messages.
class CGBProxy extends ROPlayerController;

var array< delegate<ReceiveMessage> > Receivers;

simulated event PostBeginPlay()
{
    super(PlayerController).PostBeginPlay();

    if (PlayerReplicationInfo == none)
    {
        InitPlayerReplicationInfo();
    }

    `cgblog(self @ "initialized");
}

delegate ReceiveMessage(PlayerReplicationInfo Sender, string Msg, name Type);

function AddReceiver(delegate<ReceiveMessage> ReceiveMessageDelegate)
{
    if (Receivers.Find(ReceiveMessageDelegate) == INDEX_NONE)
    {
        Receivers[Receivers.Length] = ReceiveMessageDelegate;
    }
}

function ClearReceiver(delegate<ReceiveMessage> ReceiveMessageDelegate)
{
    local int RemoveIndex;
    RemoveIndex = Receivers.Find(ReceiveMessageDelegate);
    if (RemoveIndex != INDEX_NONE)
    {
        Receivers.Remove(RemoveIndex, 1);
    }
    if (Receivers.Length == 0 && ReceiveMessage == none)
    {
        Destroy();
    }
}

function HandleMessage(
    PlayerReplicationInfo PRI,
    coerce string S,
    name Type,
    optional float MsgLifeTime)
{
    local delegate<ReceiveMessage> ReceiveMessageDelegate;

    foreach Receivers(ReceiveMessageDelegate)
    {
        ReceiveMessageDelegate(PRI, S, Type);
    }

    if (ReceiveMessage != none)
    {
        ReceiveMessage(PRI, S, Type);
    }
}

reliable client event TeamMessage(
    PlayerReplicationInfo PRI,
    coerce string S,
    name Type,
    optional float MsgLifeTime)
{
    HandleMessage(PRI, S, Type, MsgLifeTime);
}

event InitializeStats()
{
}

simulated function ReceivedGameClass(class<GameInfo> GameClass)
{
}

function SpawnDefaultHUD()
{
}

reliable client function ClientSetHUD(class<HUD> newHUDType)
{
}

reliable client function ClientRestart(Pawn NewPawn)
{
    super(PlayerController).ClientRestart(NewPawn);
}

function InitPlayerReplicationInfo()
{
    super.InitPlayerReplicationInfo();
    PlayerReplicationInfo.PlayerName = "<<ChatGPTBotsProxy>>";
    // TODO: check if non-unique name is ok?
    // PlayerReplicationInfo.PlayerName = "<<WebAdmin>>";
    PlayerReplicationInfo.bIsInactive = true;
    PlayerReplicationInfo.bIsSpectator = true;
    PlayerReplicationInfo.bOnlySpectator = true;
    PlayerReplicationInfo.bOutOfLives = true;
    PlayerReplicationInfo.bWaitingPlayer = false;

    // TODO: double-check.
    PlayerReplicationInfo.Team.TeamIndex = `NEUTRAL_TEAM_INDEX;
}

auto state NotPlaying
{}

function EnterStartState()
{
    GotoState('NotPlaying');
}

function bool IsSpectating()
{
    return true;
}

reliable client function ClientGameEnded(Actor EndGameFocus, bool bIsWinner)
{
}

function GameHasEnded(optional Actor EndGameFocus, optional bool bIsWinner)
{
}

function Reset()
{
}

reliable client function ClientReset()
{
}

event InitInputSystem()
{
    if (PlayerInput == None)
    {
        Assert(InputClass != None);
        PlayerInput = new(Self) InputClass;
    }

    if (Interactions.Find(PlayerInput) == -1)
    {
        Interactions[Interactions.Length] = PlayerInput;
    }
}

event PlayerTick(float DeltaTime)
{
    // This is needed because PlayerControllers with no actual player attached
    // will leak during seamless traveling.
    if (WorldInfo.NextURL != "" || WorldInfo.IsInSeamlessTravel())
    {
        Destroy();
    }
}

function bool CanRestartPlayer()
{
    return false;
}

simulated function CreateVoicePacks(byte TeamIndex)
{
}

function bool AllowTextMessage(string Msg)
{
    return true;
}

DefaultProperties
{
    bIsPlayer=false
    CameraClass=none
    bAlwaysTick=true
}
