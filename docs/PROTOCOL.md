# NEON ARENA TCP Protocol

TCP is the push-based transport for Agents and terminal spectators. The default endpoint is `server-ip:7777`; protocol version is `1`.

The built-in TCP transport is plaintext. An HTTP TLS reverse proxy protects only the HTTP API on port 8080; it does not protect TCP 7777. Use a trusted LAN/VPN, SSH tunnel or local forwarding, or a TLS wrapper capable of carrying raw TCP for remote Agent/spectator connections.

## Transport conventions

- One UTF-8 JSON object per line (NDJSON), terminated by `\n`.
- Maximum line size: 65,536 bytes. Oversized lines close the connection.
- Every message must be a JSON object with a non-empty string `type`.
- The server pushes messages; clients must keep reading. Do not assume strict request/response pairing.
- Unknown fields should be ignored. Unknown message types sent by a client receive `error` and the connection remains open.
- Coordinates are `[x,y]`, origin top-left, x right, y down.
- Directions: `n` = `[0,-1]`, `e` = `[1,0]`, `s` = `[0,1]`, `w` = `[-1,0]`.
- A pre-join connection with no message for 120 seconds is closed. Joined connections have no application idle timeout.
- Per-connection token bucket: 30 messages, refills at 30/second, burst 30. Excess messages receive `rate_limited` and are not processed.
- The reference SDK disables socket read timeouts after connection establishment so 30/60-second decision windows work.

## Message overview

| Direction | Type | Purpose |
| --- | --- | --- |
| Server -> client | `welcome` | Protocol/server/connection identity |
| Client -> server | `join` | Join the player lobby |
| Server -> client | `joined` | Confirmed player identity |
| Server -> client | `lobby` | Queue, effective minimum/maximum, countdown, next mode |
| Client -> server | `spectate` | Subscribe as a read-only spectator |
| Server -> client | `spectating` | Spectator subscription confirmed |
| Client -> server | `action` | Submit an action for the open turn |
| Server -> client | `action_ack` | Action accepted into the pending set |
| Server -> client | `start` | Static match rules/map/players/mode |
| Server -> client | `state` | Current turn, visible state, events, deadline |
| Server -> client | `end` | Final reason/winner/standings/mode result |
| Client -> server | `leave` | Leave lobby/match/spectator role |
| Server -> client | `left` | Leave confirmed |
| Client -> server | `ping` | Optional heartbeat/latency probe |
| Server -> client | `pong` | Heartbeat response |
| Server -> client | `error` | Recoverable validation/rate/server error |

## Connection, join, and lobby

On connect:

```json
{"type":"welcome","server":"Neon Arena","protocol":1,"client_id":"c-7f3a"}
```

Join:

```json
{"type":"join","protocol":1,"name":"Alpha"}
```

Success:

```json
{"type":"joined","protocol":1,"name":"Alpha","kind":"agent"}
```

Names are stripped, must contain 1–20 characters, and must not contain Unicode control characters. Names are unique case-insensitively among waiting players, the active match, and spectators; duplicates receive `-2`, `-3`, etc. Use `joined.name` as the final display name.

A player already in the lobby/match cannot join again on the same connection and receives `already_joined`. After a match ends, the TCP connection remains open and may `join` again.

Lobby:

```json
{
  "type": "lobby",
  "players": [
    {"name": "Alpha", "kind": "agent"},
    {"name": "Alice", "kind": "human"}
  ],
  "min_players": 2,
  "max_players": 4,
  "starts_in_ms": 4200,
  "mode": "classic",
  "mode_label": "Classic",
  "mode_description": "Last player standing or highest score."
}
```

| Field | Meaning |
| --- | --- |
| `players` | FIFO queue entries with `name` and `kind` (`human`/`agent`) |
| `min_players` | Effective minimum: larger of server minimum and selected mode minimum |
| `max_players` | Configured maximum, at most 4 |
| `starts_in_ms` | Remaining countdown, or `null` when the minimum is not met/no countdown is active |
| `mode` | Actual next playable mode, not merely the configured `rotation` value |
| `mode_label` | Display name |
| `mode_description` | One-line mode description |

Rotation order is `classic -> king -> team -> survival -> bounty`. With 2–3 waiting players, `team` is skipped. With 4 it is eligible. A fixed `--mode` does not rotate.

## Spectating

```json
{"type":"spectate"}
```

```json
{"type":"spectating","match_running":true}
```

If a match is running, the server immediately follows with a `start` and current `state`, both without `you`. If no match is running, the spectator receives lobby broadcasts and then future `start` messages. Spectators do not occupy player slots and cannot submit actions. Spectator `join`/`spectate` role conflicts receive `already_joined`. Spectator disconnect does not forfeit anyone.

## Match start

`start` is sent once per match. Participant copies include `you`; spectator copies omit it.

| Field | Meaning |
| --- | --- |
| `type` | `start` |
| `protocol` | `1` |
| `match_id` | Unique match identifier |
| `seed` | Map-generation seed |
| `turn_limit` | Configured completed-turn limit |
| `rules` | Authoritative numeric rules |
| `arena` | `width`, `height`, `walls`, `nodes`, `spawns` |
| `players` | Initial `id`, `name`, `kind`, `pos` |
| `mode` | `classic`, `king`, `team`, `survival`, or `bounty` |
| `mode_state` | Public mode state |
| `tick_ms` | Shared maximum decision window |
| `min_turn_ms` | Minimum delay after all living players submit |
| `you` | Participant player ID; absent for spectators |

```json
{
  "type": "start",
  "protocol": 1,
  "match_id": "m-20261124-142501-a1b2",
  "seed": 74128831,
  "turn_limit": 80,
  "tick_ms": 15000,
  "min_turn_ms": 250,
  "mode": "king",
  "mode_state": {
    "zone": {"min": [6, 6], "max": [8, 8]},
    "target_score": 100,
    "streaks": {"P1": 0, "P2": 0}
  },
  "rules": {
    "max_hp": 100,
    "max_energy": 100,
    "start_energy": 40,
    "energy_regen": 4,
    "attack": {"cost": 8, "damage": 22},
    "dash": {"cost": 18, "distance": 2},
    "heal": {"cost": 25, "amount": 25},
    "shield": {"cost": 12, "amount": 26, "max": 40},
    "gather": {"energy": 30, "node_cooldown": 4},
    "score": {"damage": 1, "kill": 25, "gather": 10},
    "turn_limit": 80
  },
  "arena": {
    "width": 15,
    "height": 15,
    "walls": [],
    "nodes": [[7,7],[7,3],[3,7],[11,7],[7,11]],
    "spawns": [[1,1],[13,13],[13,1],[1,13]]
  },
  "players": [
    {"id": "P1", "name": "Alpha", "kind": "agent", "pos": [1,1]},
    {"id": "P2", "name": "Alice", "kind": "human", "pos": [13,13]}
  ],
  "you": "P1"
}
```

## Turn state

| Field | Meaning |
| --- | --- |
| `type` | `state` |
| `match_id` | Match identifier |
| `turn` | Current decision turn, starting at 1 |
| `turn_limit` | Completed-turn limit |
| `tick_ms` | Shared maximum window |
| `reply_by_ms` | Absolute Unix-millisecond submission deadline |
| `players` | Full player snapshots |
| `nodes` | `pos`, `cooldown`, `active` for each node |
| `events_turn` | Turn that produced `events`; 0 on the first state. An immediate out-of-turn forfeit snapshot uses the current open turn. |
| `events` | Previous completed turn's events; empty on the first state. An immediate forfeit snapshot contains the forfeit event instead. |
| `mode` | Current mode |
| `mode_state` | Current public mode state |
| `you` | Participant player ID; absent for spectators |

Player snapshots always contain:

```json
{
  "id": "P1",
  "name": "Alpha",
  "kind": "agent",
  "pos": [2,1],
  "hp": 100,
  "shield": 0,
  "energy": 44,
  "score": 0,
  "alive": true,
  "stats": {"damage_dealt": 0, "kills": 0, "gathered": 0, "forfeited": false}
}
```

Optional mode fields:

| Field | Mode | Meaning |
| --- | --- | --- |
| `team` | `team` | `T1` or `T2` |
| `hill_streak` | `king` | Consecutive completed turns in the hill zone |
| `in_storm` | `survival` | Whether the player's current position is outside the safe zone |
| `bounty_target` | `bounty` | Assigned living target ID, or `null` when dead/no target |
| `bounty_streak` | `bounty` | Consecutive assigned-target kills |

Dead or forfeited participants who remain attached (for example, after missed-turn forfeits) still receive snapshots but cannot act. Explicit `leave`, TCP disconnect, and HTTP `DELETE /sessions` detach the participant, which receives no further old-match messages. After the last turn, the server sends attached participants `end` instead of another `state`; final events are in `end.events`.

## Mode state

| Mode | Shape |
| --- | --- |
| `classic` | `{}` |
| `king` | `{"zone":{"min":[6,6],"max":[8,8]},"target_score":100,"streaks":{"P1":0,"P2":0}}` |
| `team` | `{"teams":[{"id":"T1","name":"Team A","members":["P1","P2"],"score":0,"alive":2},{"id":"T2","name":"Team B","members":["P3","P4"],"score":0,"alive":2}]}` |
| `survival` | `{"zone":{"min":[1,1],"max":[13,13]},"next_shrink_turn":6,"storm_damage":12}` |
| `bounty` | `{"target_score":150,"targets":{"P1":"P2","P2":"P3","P3":"P1"}}` |

Clients must treat `mode_state` as public state, not instructions to simulate outcomes locally. The server remains authoritative.

## Action submission

```json
{"type":"action","turn":6,"action":{"type":"attack","dir":"e"}}
```

Accepted:

```json
{"type":"action_ack","turn":6,"action":{"type":"attack","dir":"e"}}
```

Action forms:

```json
[
  {"type":"move","dir":"n|e|s|w"},
  {"type":"dash","dir":"n|e|s|w"},
  {"type":"attack","dir":"n|e|s|w"},
  {"type":"gather"},
  {"type":"shield"},
  {"type":"heal"},
  {"type":"wait"}
]
```

- `turn` must be an integer and equal the current open turn.
- A legal resubmission replaces the player's earlier pending action.
- `stale_turn` means the supplied turn is not current.
- `turn_closed` means the turn has resolved or its deadline has passed.
- Rejected actions consume no resources and can be corrected while the turn remains open.
- A missing/invalid action at resolution becomes `wait` and increments the miss count; four consecutive misses forfeit.

## Strict deadline semantics

The deadline is shared by every participant. It is not extended for an Agent, LLM, slow network, or human. `reply_by_ms` is absolute Unix time; clients may compare it with `server.now_ms` from HTTP or estimate clock offset.

The reference SDK checks the deadline before and after `Policy.decide`. If an action is produced at or after the deadline, it is recorded only in `ArenaClient.expired_actions` as:

```json
{"turn":6,"action":{"type":"wait"},"reason":"turn_deadline_passed"}
```

It is not sent and is not replayed on a later turn. The server independently rejects late submissions with `turn_closed`, so no late action changes an already resolved turn.

For LLM play, use server `--tick-ms 30000` or `--tick-ms 60000` and set `NEON_ARENA_LLM_TIMEOUT_MS` to `24000` or `48000`, respectively, in the Agent environment. The bundled LLM bot caps requests at the smallest of that configured timeout, 80% of `tick_ms`, and 90% of the remaining deadline, with heuristic fallback for parsing/HTTP/timeout failures.

## Events

`events` normally describes one completed turn. First-turn states use `events: []` and `events_turn: 0`. An immediate out-of-turn forfeit snapshot is the exception: it may carry the `forfeit` event with `turn` and `events_turn` equal to the current open turn, without incrementing the completed-turn count. Final-turn events are repeated in `end.events`.

| Event type | Fields | Meaning |
| --- | --- | --- |
| `move` | `player, from, to` | Successful one-cell move |
| `dash` | `player, from, to` | Successful two-cell dash |
| `blocked` | `player, action, dir, reason` | Move/dash blocked; reason `occupied` or `collision` |
| `attack` | `player, dir, target` | Attack declared; target coordinate or `null` |
| `damage` | `player, target, hp_damage, shield_damage` | Damage applied; bounty mode may add `bounty: true` |
| `heal` | `player, amount, hp` | HP restored |
| `shield` | `player, amount, shield` | Shield gained |
| `gather` | `player, pos, energy_gain, score_gain` | Node gathered |
| `death` | `player, killer` | Elimination; `killer` may be `null` |
| `forfeit` | `player` | Explicit leave/disconnect/delete or missed-turn forfeit |
| `hill_score` | `player, pos, points, streak, score` | King zone score awarded |
| `friendly_blocked` | `player, target` | Team attack blocked |
| `storm_shrink` | `zone, next_shrink_turn` | Survival zone changed |
| `storm_damage` | `player, amount, hp` | True storm HP damage |
| `bounty_complete` | `player, target, bonus, streak` | Assigned target killed |
| `bounty_retarget` | `player, target` | Living player's target changed after resolution |

Clients should render unknown future event types safely rather than fail the connection.

## End message

```json
{
  "type": "end",
  "match_id": "m-20261124-142501-a1b2",
  "reason": "turn_limit",
  "turns": 80,
  "winner": {"id": "P2", "name": "Alice"},
  "standings": [],
  "events_turn": 80,
  "events": [],
  "mode": "classic",
  "mode_state": {}
}
```

| Field | Meaning |
| --- | --- |
| `reason` | `last_standing`, `mutual_destruction`, `score_limit`, `turn_limit`, or `aborted` |
| `turns` | Number of completed turns |
| `winner` | Player `{id,name}`, team `{id,name,kind:"team",members}`, or `null` for `aborted` |
| `standings` | Final player snapshots, ranked |
| `events_turn` / `events` | Normally the final completed turn and its events; for an out-of-turn forfeit, the current open turn and forfeit event |
| `mode` / `mode_state` | Final mode and public state |
| `team_standings` | Team mode only; ranked team aggregates including `hp` and `energy` |

After `end`, the connection remains open. Send `join` again to enter a new lobby; there is no automatic continuous match.

## Leave, heartbeat, and errors

Leave:

```json
{"type":"leave"}
```

```json
{"type":"left"}
```

Leaving the lobby removes the player. Leaving an active match forfeits and detaches that participant; the participant receives `left` and no further delivery from the old match. Other participants continue if the match is not over. A spectator leave only removes the subscription. The same connection may join/spectate again afterward.

Heartbeat:

```json
{"type":"ping","ts":123}
```

```json
{"type":"pong","ts":123}
```

`ts` is optional and echoed unchanged when present.

Error:

```json
{"type":"error","code":"turn_closed","message":"the turn deadline has passed","turn":6}
```

`turn` is included when the rejected message carried an integer turn.

| Code | Meaning |
| --- | --- |
| `bad_json` | Line is not valid JSON |
| `invalid_message` | Message is not an object with a string `type`, or a message field has the wrong type |
| `protocol_mismatch` | Unsupported protocol version |
| `invalid_name` | Empty, too long, or control-character name |
| `already_joined` | Connection already has a lobby/match/spectator role |
| `not_joined` | Action sent before joining as a player |
| `not_in_match` | Player is not in an active match |
| `not_alive` | Eliminated player cannot act |
| `stale_turn` | Turn does not equal the current turn |
| `turn_closed` | Turn is resolved or deadline has passed |
| `invalid_action` | Invalid action object/type/direction |
| `insufficient_energy` | Action cost exceeds energy |
| `wall` | Move/dash target or path is not walkable |
| `no_active_node` | Gather is not on an active node |
| `full_hp` | Heal attempted at full HP |
| `shield_full` | Shield attempted at maximum |
| `server_full` | Connection/lobby capacity reached |
| `rate_limited` | TCP message rate exceeded |
| `internal_error` | Unexpected server error |

The HTTP layer also defines `out_of_bounds` in its status mapping, but the current engine's movement validator emits `wall` for border failures.

## Disconnect semantics

- TCP player disconnect in a match immediately sets `alive=false`, `hp=0`, `stats.forfeited=true`, emits `forfeit`, and checks whether the match ends. No killer is credited.
- An out-of-turn forfeit may emit an immediate `state` snapshot/log record to remaining participants and spectators. Its `turn` and `events_turn` equal the current open turn, and its `events` contain the forfeit; `completed_turns` does not advance.
- In team mode, one disconnected member does not end the match while a teammate remains alive.
- TCP lobby disconnect removes the queued player; spectator disconnect only removes the spectator.
- TCP connection loss provides no `left` message because the socket is gone.
- HTTP behavior is different: closing the page does not immediately forfeit; explicit `DELETE /sessions` does. See [HTTP_API.md](HTTP_API.md).

## Complete two-turn match example

This compact transcript uses the current engine with `Rules(turn_limit=2)`, players `[("Alpha", "agent"), ("Alice", "human")]`, `seed=7`, `match_id="m-example"`, and `mode="classic"`. The map walls/spawns, player positions, actions, events, energy values, and winner below are exact engine output; repeated player/node details are abbreviated. The `reply_by_ms` values are illustrative transport timestamps.

```text
S->Alpha welcome {protocol:1,client_id:"c-a1"}
C->Alpha join {protocol:1,name:"Alpha"}
S->Alpha joined {protocol:1,name:"Alpha",kind:"agent"}
S->Alpha lobby {players:[Alpha],min_players:2,max_players:4,starts_in_ms:null,
                mode:"classic",mode_label:"Classic",mode_description:"Last player standing or highest score."}

S->Alice welcome {protocol:1,client_id:"c-b2"}
C->Alice join {protocol:1,name:"Alice"}
S->Alice joined {protocol:1,name:"Alice",kind:"human"}
S->Alpha/Alice lobby {players:[Alpha,Alice],min_players:2,max_players:4,starts_in_ms:5000,
                      mode:"classic",mode_label:"Classic",mode_description:"Last player standing or highest score."}

S->Alpha start {type:"start",protocol:1,match_id:"m-example",seed:7,turn_limit:2,tick_ms:15000,min_turn_ms:250,
                rules:{max_hp:100,max_energy:100,start_energy:40,energy_regen:4,
                       attack:{cost:8,damage:22},dash:{cost:18,distance:2},
                       heal:{cost:25,amount:25},shield:{cost:12,amount:26,max:40},
                       gather:{energy:30,node_cooldown:4},score:{damage:1,kill:25,gather:10},turn_limit:2},
                arena:{width:15,height:15,
                       walls:[[1,6],[1,7],[3,9],[4,2],[4,5],[5,1],[5,5],[5,13],[6,13],
                              [7,1],[7,13],[8,1],[9,1],[9,9],[9,13],[10,9],[10,12],[11,5],[13,7],[13,8]],
                       nodes:[[7,7],[7,3],[3,7],[11,7],[7,11]],
                       spawns:[[1,1],[13,13],[13,1],[1,13]]},
                players:[{id:"P1",name:"Alpha",kind:"agent",pos:[13,1]},
                         {id:"P2",name:"Alice",kind:"human",pos:[1,13]}],
                mode:"classic",mode_state:{},you:"P1"}
S->Alice start {same fields,you:"P2"}

S->Alpha state {type:"state",match_id:"m-example",turn:1,turn_limit:2,tick_ms:15000,reply_by_ms:1763890015000,
                players:[P1@(13,1) HP100 Energy40,P2@(1,13) HP100 Energy40],
                nodes:[five active nodes],events_turn:0,events:[],mode:"classic",mode_state:{},you:"P1"}
S->Alice state {same state,you:"P2"}

C->Alpha action {turn:1,action:{type:"move",dir:"w"}}
S->Alpha action_ack {turn:1,action:{type:"move",dir:"w"}}
C->Alice action {turn:1,action:{type:"wait"}}
S->Alice action_ack {turn:1,action:{type:"wait"}}

S->Alpha/Alice state {type:"state",match_id:"m-example",turn:2,turn_limit:2,tick_ms:15000,reply_by_ms:1763890030000,
                      players:[P1@(12,1) HP100 Energy44,P2@(1,13) HP100 Energy44],
                      nodes:[five active nodes],events_turn:1,
                      events:[{type:"move",player:"P1",from:[13,1],to:[12,1]}],
                      mode:"classic",mode_state:{}}

C->Alpha action {turn:2,action:{type:"attack",dir:"w"}}
S->Alpha action_ack {turn:2,action:{type:"attack",dir:"w"}}
C->Alice action {turn:2,action:{type:"wait"}}
S->Alice action_ack {turn:2,action:{type:"wait"}}

S->Alpha/Alice end {type:"end",match_id:"m-example",reason:"turn_limit",turns:2,
                    winner:{id:"P2",name:"Alice"},
                    standings:[P2@(1,13) Energy48,P1@(12,1) Energy40],events_turn:2,
                    events:[{type:"attack",player:"P1",dir:"w",target:null}],
                    mode:"classic",mode_state:{}}

C->Alpha ping {ts:"done"}
S->Alpha pong {ts:"done"}
C->Alpha leave
S->Alpha left
```

For a full machine-readable example, use the schemas in [openapi.yaml](openapi.yaml) for shared player/action/result shapes and the field tables above for TCP envelopes.
