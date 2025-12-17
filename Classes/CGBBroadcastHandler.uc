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

// Custom broadcast handler to capture all messages via our custom CGBProxy.
class CGBBroadcastHandler extends ROBroadcastHandler
    DependsOn(CGBProxy);

function bool AllowsBroadcast(Actor Broadcaster, int InLen)
{
    // Always allow incoming messages from the LLM.
    if (Broadcaster.IsA(NameOf(class'CGBProxy')))
    {
        return True;
    }

    return Super.AllowsBroadcast(Broadcaster, InLen);
}

function Broadcast(Actor Sender, coerce string Msg, optional name Type)
{
    local PlayerController PC;
    local PlayerReplicationInfo PRI;
    local CGBProxy CProxy;

    if (Pawn(Sender) != None)
    {
        PRI = Pawn(Sender).PlayerReplicationInfo;
    }
    else if (Controller(Sender) != None)
    {
        PRI = Controller(Sender).PlayerReplicationInfo;
    }

    // Other types should have been handled in their respective handlers.
    if (Type == 'Say')
    {
        foreach WorldInfo.AllControllers(class'CGBProxy', CProxy)
        {
            BroadcastText(PRI, CProxy, Msg, Type);
        }
    }

    // See if allowed (limit to prevent spamming).
    if (!AllowsBroadcast(Sender, Len(Msg)))
    {
        return;
    }

    foreach WorldInfo.AllControllers(class'PlayerController', PC)
    {
        BroadcastText(PRI, PC, FilterMessage(Msg), Type);
    }
}

function BroadcastTeam(Controller Sender, coerce string Msg, optional name Type)
{
    local PlayerController PC;
    local CGBProxy CProxy;

    foreach WorldInfo.AllControllers(class'CGBProxy', CProxy)
    {
        BroadcastText(Sender.PlayerReplicationInfo, CProxy, Msg, Type);
    }

    if (!AllowsBroadcast(Sender, Len(Msg)))
    {
        return;
    }

    foreach WorldInfo.AllControllers(class'PlayerController', PC)
    {
        if (PC.PlayerReplicationInfo.Team == Sender.PlayerReplicationInfo.Team)
        {
            BroadcastText(Sender.PlayerReplicationInfo, PC, FilterMessage(Msg), Type);
        }
    }
}

function BroadcastSquad(Controller Sender, coerce string Msg, optional name Type)
{
    local int i;
    local ROPlayerController ROPC;
    local ROPlayerReplicationInfo ROPRISender;
    local ROSquadInfo Squad;
    local CGBProxy CProxy;
    local bool bSentToPilot;

    foreach WorldInfo.AllControllers(class'CGBProxy', CProxy)
    {
        BroadcastText(Sender.PlayerReplicationInfo, CProxy, Msg, Type);
    }

    // see if allowed (limit to prevent spamming)
    if (!AllowsBroadcast(Sender, Len(Msg)))
    {
        return;
    }

    ROPRISender = ROPlayerReplicationInfo(Sender.PlayerReplicationInfo);
    Squad = ROPRISender.Squad;

    if (Squad != none)
    {
        Msg = FilterMessage(Msg);

        // Send to all squad members.
        for (i = 0; i < `MAX_ROLES_PER_SQUAD; ++i)
        {
            ROPC = ROPlayerController(Squad.SquadMembers[i].Owner);
            if (ROPC != none)
            {
                BroadcastText(ROPRISender, ROPC, Msg, Type);

                // If the pilot attached to this squad is also a member of this squad,
                // don't send them duplicate messages.
                if (ROPC == Squad.AttachedPilot.Owner)
                {
                    bSentToPilot = true;
                }
            }
        }

        // Send to the squad's attached pilot.
        if (!bSentToPilot)
        {
            ROPC = ROPlayerController(Squad.AttachedPilot.Owner);
            if (ROPC != none)
            {
                // Change the message type for these messages to be
                // "attached squad say" instead.
                BroadcastText(ROPRISender, ROPC, Msg, 'ASquadSay');
            }
        }
    }
}

// Special handler for the Pilots Only squad, which isn't actually a real squad, so can't use the regular Squad handler.
function BroadcastPilotSquad(Controller Sender, coerce string Msg, optional name Type)
{
    local ROPlayerController ROPC;
    local CGBProxy CProxy;

    foreach WorldInfo.AllControllers(class'CGBProxy', CProxy)
    {
        BroadcastText(Sender.PlayerReplicationInfo, CProxy, Msg, Type);
    }

    // see if allowed (limit to prevent spamming)
    if (!AllowsBroadcast(Sender, Len(Msg)))
    {
        return;
    }

    foreach WorldInfo.AllControllers(class'ROPlayerController', ROPC)
    {
        if (ROPC.PlayerReplicationInfo.Team == Sender.PlayerReplicationInfo.Team
            && ROPlayerReplicationInfo(ROPC.PlayerReplicationInfo) != none
            && ROPlayerReplicationInfo(ROPC.PlayerReplicationInfo).SquadIndex == `SQUAD_INDEX_PILOT)
        {
            BroadcastText(Sender.PlayerReplicationInfo, ROPC, Msg, Type);
        }
    }
}

function NotifyWebAdmins(string msg)
{
    local Admin WebAdm;

    // Send a message to all web-admin chats.
    foreach WorldInfo.AllControllers(class'Admin', WebAdm)
    {
        if (!WebAdm.IsA('TeamChatProxy') && !webAdm.IsA('CGBProxy'))
        {
            WebAdm.TeamMessage(None, msg, '');
        }
    }
}
