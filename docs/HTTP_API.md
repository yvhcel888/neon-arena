# NEON ARENA HTTP API

The HTTP API is the human/custom-client interface to the authoritative server. The reference Web client uses it independently; the server does not serve that client.

- Base URL: `http://<server-ip>:8080/api/v1`
- Default local URL: `http://127.0.0.1:8080/api/v1`
- Media type: `application/json; charset=utf-8`
- API version: URL prefix `/api/v1`
- Authentication: `Authorization: Bearer <token>` for session/state/action/delete operations
- No cookies or account system

OpenAPI 3.0.3 description: [openapi.yaml](openapi.yaml).

## Common response envelope

Success:

```json
{"ok": true}
```

Success with data adds fields beside `ok`, such as `token`, `view`, `turn`, or `action`.

Error:

```json
{
  "ok": false,
  "error": {
    "code": "turn_closed",
    "message": "the turn deadline has passed"
  }
}
```

Every response includes `Content-Type`, `Content-Length`, `Connection: close`, and the configured CORS headers. HTTP `204` preflight responses have no body.

The server root, `/client/*`, and all unknown paths return `404` with the JSON error envelope. They never return HTML, CSS, JavaScript, directory listings, or client files.

## CORS

Default headers:

```text
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type
Access-Control-Max-Age: 600
```

`--cors-origin` accepts one origin or comma-separated origins. With an allowlist, the server echoes `Access-Control-Allow-Origin` only when the request's `Origin` is allowed. `Access-Control-Allow-Credentials` is not used.

`OPTIONS` returns `204` without authentication or game-state changes. Error responses use the same CORS policy as success responses.

## Endpoints

| Method | Path | Auth | Success | Purpose |
| --- | --- | --- | ---: | --- |
| GET | `/health` | No | 200 | Health, version, protocol, counters |
| GET | `/rules` | No | 200 | Rules and public server defaults |
| POST | `/sessions` | Optional | 200 | Create/recover a human session and queue |
| GET | `/state` | Yes | 200 | Poll lobby/match/ended view |
| POST | `/actions` | Yes | 200 | Submit one action for the open turn |
| DELETE | `/sessions` | Yes | 200 | Leave/forfeit and invalidate token |
| OPTIONS | Any path | No | 204 | CORS preflight |

### GET /health

No authentication.

```json
{
  "ok": true,
  "server": "Neon Arena",
  "version": "1.0.0",
  "protocol": 1,
  "uptime_s": 3721,
  "lobby_players": 2,
  "match_running": true,
  "active_players": 3,
  "spectators": 1
}
```

`active_players` counts non-detached participants in the active match. `uptime_s` is integer seconds since server construction.

### GET /rules

No authentication.

```json
{
  "ok": true,
  "protocol": 1,
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
  "defaults": {
    "tick_ms": 15000,
    "min_turn_ms": 250,
    "turn_limit": 80,
    "min_players": 2,
    "max_players": 4,
    "mode": "rotation"
  }
}
```

`rules` matches TCP `start.rules`. `defaults` is the public subset of server configuration; `mode` is `rotation` or one of the five fixed modes.

### POST /sessions

Creates or recovers a human session and returns a token plus the current view.

New session, no Authorization header:

```json
{"name": "Alice"}
```

Recover an existing session, body optional/empty:

```text
Authorization: Bearer <token>
```

Response:

```json
{
  "ok": true,
  "token": "<token>",
  "view": {
    "mode": "lobby",
    "you": {"id": null, "name": "Alice", "kind": "human"},
    "server": {"version": "1.0.0", "protocol": 1, "now_ms": 1763890000000},
    "lobby": {
      "players": [{"name": "Alice", "kind": "human"}],
      "min_players": 2,
      "max_players": 4,
      "starts_in_ms": null,
      "mode": "classic",
      "mode_label": "Classic",
      "mode_description": "Last player standing or highest score."
    },
    "match": null,
    "result": null
  }
}
```

Behavior:

- New request: validates the name, creates a `kind=human` participant, queues it, and returns a URL-safe token.
- Valid token in lobby/match: returns the same session and current view without creating a duplicate.
- Valid token in ended/idle state: re-queues the participant, clears the frozen result, and returns the lobby/match view. This is the “Play again” operation.
- Invalid token without `name`: `401 unauthorized`.
- Invalid token with `name`: creates a new session; clients should discard the old token.
- Name rules match TCP: trimmed, 1–20 characters, no control characters, case-insensitive duplicate suffixing.
- Combined TCP connections and HTTP sessions are capped by `--max-clients` (default 32); excess returns `503 server_full`.

### GET /state

Requires `Authorization: Bearer <token>`.

```json
{"ok": true, "view": {"mode": "match", "you": {}, "server": {}, "lobby": null, "match": {}, "result": null}}
```

The actual view is one of the three shapes below. Polling also refreshes the session's `last_poll` activity.

### POST /actions

Requires `Authorization: Bearer <token>`.

Request:

```json
{"turn": 6, "action": {"type": "attack", "dir": "e"}}
```

Response:

```json
{"ok": true, "turn": 6, "action": {"type": "attack", "dir": "e"}}
```

Allowed action objects:

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

Rules:

- `turn` must be an integer, not a boolean, and must equal the current turn.
- Unknown fields in the request object or action object are ignored; required fields and action values are still validated.
- A legal resubmission replaces the pending action for that turn.
- `stale_turn` is `409` when the turn does not match.
- `turn_closed` is `409` after resolution or at/after `reply_by_ms`.
- `not_in_match` and `not_alive` are `409`.
- Invalid shape/resources/position are `400`; rejected actions spend no resources.
- Missing/invalid actions at resolution become `wait` and count toward the four-miss forfeit.

The server is authoritative even if a client believes an action is legal.

### DELETE /sessions

Requires `Authorization: Bearer <token>`.

```json
{"ok": true}
```

- Lobby: removes the participant from the queue.
- Active match: immediately forfeits the participant, then detaches them. Remaining participants/spectators may receive an immediate state snapshot/log record whose `turn` and `events_turn` equal the current open turn.
- Ended/idle: removes the retained session/result.
- The token is invalidated in all cases; subsequent requests receive `401`.
- The response contains no frozen match result.

## State view

All views contain `mode`, `you`, `server`, `lobby`, `match`, and `result`. Exactly one of `lobby`, `match`, or `result` carries the active payload.

### Lobby view

```json
{
  "mode": "lobby",
  "you": {"id": null, "name": "Alice", "kind": "human"},
  "server": {"version": "1.0.0", "protocol": 1, "now_ms": 1763890000000},
  "lobby": {
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
  },
  "match": null,
  "result": null
}
```

`you.id` is `null` in the lobby. `lobby.mode` is the actual next playable mode; with 2–3 players, rotation skips `team`. `starts_in_ms` is `null` until the effective minimum is met and a countdown exists.

### Match view

```json
{
  "mode": "match",
  "you": {"id": "P2", "name": "Alice", "kind": "human"},
  "server": {"version": "1.0.0", "protocol": 1, "now_ms": 1763890000000},
  "lobby": null,
  "match": {
    "match_id": "m-20261124-142501-a1b2",
    "seed": 74128831,
    "turn": 6,
    "turn_limit": 80,
    "tick_ms": 15000,
    "reply_by_ms": 1763890015000,
    "rules": {},
    "arena": {},
    "players": [],
    "nodes": [],
    "events_turn": 5,
    "events": [],
    "mode": "bounty",
    "mode_state": {"target_score": 150, "targets": {"P1": "P2", "P2": "P1"}},
    "submitted": false,
    "your_action": null
  },
  "result": null
}
```

`match` combines TCP `start` static data with TCP `state` dynamic data and adds:

| Field | Meaning |
| --- | --- |
| `submitted` | Whether this participant currently has a pending action |
| `your_action` | Pending normalized action, or `null` |

`reply_by_ms` is the shared absolute deadline. Compare it with `server.now_ms` to reduce clock-skew error. `events` normally contains the previous completed turn; an immediate out-of-turn forfeit snapshot instead contains the forfeit event with `events_turn` equal to the current open turn. The final turn's events appear in `result.events`.

Player entries contain `id`, `name`, `kind`, `pos`, `hp`, `shield`, `energy`, `score`, `alive`, and `stats`. Mode-specific optional fields are `team`, `hill_streak`, `in_storm`, `bounty_target`, and `bounty_streak`.

### Ended view

```json
{
  "mode": "ended",
  "you": {"id": "P2", "name": "Alice", "kind": "human"},
  "server": {"version": "1.0.0", "protocol": 1, "now_ms": 1763890080000},
  "lobby": null,
  "match": {},
  "result": {
    "type": "end",
    "match_id": "m-20261124-142501-a1b2",
    "reason": "score_limit",
    "turns": 20,
    "winner": {"id": "P1", "name": "Alpha"},
    "standings": [],
    "events_turn": 20,
    "events": [],
    "mode": "bounty",
    "mode_state": {"target_score": 150, "targets": {"P1": null, "P2": "P1"}}
  }
}
```

`result.reason` is one of `last_standing`, `mutual_destruction`, `score_limit`, `turn_limit`, or `aborted`. `aborted` has no winner. `result.events_turn` normally identifies the final completed turn; if an out-of-turn forfeit ends the match, it identifies the current open turn while `result.turns` remains the completed-turn count.

In team mode, the winner is:

```json
{"id":"T1","name":"Team A","kind":"team","members":["P1","P2"]}
```

and `result.team_standings` contains ranked rows with `id`, `name`, `members`, `score`, `alive`, `hp`, and `energy`. Player `standings` remain present.

The frozen `match` allows the final board to remain visible. The ended view is retained for 600 seconds. POST `/sessions` with the same token re-queues the player and clears the retained result.

## Session limits and cleanup

- Per-session rolling rate limit: 20 requests per 1-second window; excess receives `429 rate_limited`.
- Lobby session with no authenticated request for more than 30 seconds is removed.
- Ended session/result older than 600 seconds is removed.
- Request header limit: 16 KiB (`431 headers_too_large`).
- Request body limit: 32 KiB (`413 body_too_large`).
- Request read timeout: 10 seconds (`408 request_timeout`).
- Chunked request bodies are unsupported (`400 unsupported_transfer_encoding`).
- An absent `Content-Length` means a zero-length body, not an error. This supports bodyless requests and token-only session recovery. A present value must be an ASCII non-negative decimal integer no greater than 32768; invalid values return `400 invalid_content_length` or `400 invalid_request` as appropriate.
- Only `GET`, `POST`, `DELETE`, and `OPTIONS` are routed; other methods receive `405 method_not_allowed`.

## Polling and mixed-match flow

Recommended polling:

| View/page | Interval |
| --- | ---: |
| Lobby | 800 ms |
| Active match | 350 ms |
| Ended | 1500 ms |
| Hidden page | 1500 ms |
| Network error | Exponential backoff, maximum 5 s |

Use a single polling chain. Continue polling after submission and show “waiting for other players”; a fast Agent never advances the turn alone. `409` responses should trigger an immediate state refresh. `401` invalidates the token; `429` should back off.

Mixed TCP/HTTP match:

```text
1. Start server (rotation or a fixed mode).
2. Start one or more TCP Agents on server-ip:7777.
3. GET  /health from the human client.
4. POST /sessions {"name":"Alice"} and retain the token.
5. GET  /state until view.mode == "match".
6. Read match.turn/mode/mode_state/rules/arena/players.
7. POST /actions for each open turn before reply_by_ms.
8. GET  /state for the next turn and events.
9. On view.mode == "ended", display result and optional team_standings.
10. POST /sessions with the same token to queue again, or DELETE to leave.
```

After a match, nothing automatically rejoins. This applies to humans and Agents.

## Five-mode client behavior

The reference client keeps the same controls in all modes:

- `classic`: standard board and status HUD.
- `king`: center-zone overlay, target score, and hill streak.
- `team`: team rings/borders/HUD and team result table.
- `survival`: storm mask, safe-zone outline, next shrink, and storm status.
- `bounty`: target line/marker and bounty streak.

It recognizes `reason == "score_limit"` and `winner.kind == "team"`. Refresh restores lobby/match/ended state from the server-scoped token. Controls are mouse/touch, WASD/arrows, `1..7`, `Space`, and `Esc`.

## PowerShell 5.1 examples

```powershell
$base = "http://127.0.0.1:8080/api/v1"

# Health and rules
$health = Invoke-RestMethod -Method Get -Uri "$base/health"
$rules = Invoke-RestMethod -Method Get -Uri "$base/rules"

# Create a human session
$body = @{ name = "Alice" } | ConvertTo-Json -Compress
$created = Invoke-RestMethod -Method Post -Uri "$base/sessions" `
  -ContentType "application/json; charset=utf-8" -Body $body
$token = $created.token
$headers = @{ Authorization = "Bearer $token" }

# Poll state
$state = Invoke-RestMethod -Method Get -Uri "$base/state" -Headers $headers
$state.view.mode
$state.view.match.turn
$state.view.match.mode

# Submit an action for the current open turn
$actionBody = @{
  turn = $state.view.match.turn
  action = @{ type = "wait" }
} | ConvertTo-Json -Depth 5 -Compress
$ack = Invoke-RestMethod -Method Post -Uri "$base/actions" `
  -Headers $headers -ContentType "application/json; charset=utf-8" -Body $actionBody

# Recover/re-queue with the same token (empty body)
$recovered = Invoke-RestMethod -Method Post -Uri "$base/sessions" -Headers $headers

# Leave and invalidate the token
Invoke-RestMethod -Method Delete -Uri "$base/sessions" -Headers $headers
```

For error inspection in PowerShell 5.1, catch `System.Net.WebException` and read `$_.Exception.Response.GetResponseStream()` with a `StreamReader`; the body is the same JSON error envelope.

## curl examples

Use `curl.exe` on Windows so PowerShell does not select its `curl` alias.

```bash
curl.exe -sS http://127.0.0.1:8080/api/v1/health
curl.exe -sS http://127.0.0.1:8080/api/v1/rules

curl.exe -sS -X POST http://127.0.0.1:8080/api/v1/sessions \
  -H "Content-Type: application/json" \
  --data "{\"name\":\"Alice\"}"

curl.exe -sS http://127.0.0.1:8080/api/v1/state \
  -H "Authorization: Bearer <token>"

curl.exe -sS -X POST http://127.0.0.1:8080/api/v1/actions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  --data "{\"turn\":1,\"action\":{\"type\":\"wait\"}}"

curl.exe -sS -X POST http://127.0.0.1:8080/api/v1/sessions \
  -H "Authorization: Bearer <token>"

curl.exe -sS -X DELETE http://127.0.0.1:8080/api/v1/sessions \
  -H "Authorization: Bearer <token>"
```

## Error reference

| HTTP | Code | Meaning |
| ---: | --- | --- |
| 400 | `invalid_json` | Body is not a JSON object |
| 400 | `invalid_name` | Name missing/invalid |
| 400 | `invalid_request` | Malformed/incomplete request |
| 400 | `unsupported_transfer_encoding` | Chunked body unsupported |
| 400 | `invalid_content_length` | Present Content-Length is not an ASCII non-negative decimal integer |
| 400 | `invalid_action` | Invalid turn/action shape |
| 400 | `insufficient_energy` | Not enough energy |
| 400 | `wall` | Movement target/path blocked by border/wall |
| 400 | `out_of_bounds` | Reserved status mapping; current engine normally emits `wall` |
| 400 | `no_active_node` | No active node at player position |
| 400 | `full_hp` | Heal at full HP |
| 400 | `shield_full` | Shield at maximum |
| 401 | `unauthorized` | Missing/invalid bearer token |
| 404 | `not_found` | Unknown path |
| 405 | `method_not_allowed` | Unsupported method for a known path |
| 408 | `request_timeout` | Request read timeout |
| 409 | `stale_turn` | Turn is not current |
| 409 | `turn_closed` | Turn resolved/deadline passed |
| 409 | `not_in_match` | Participant is not playing |
| 409 | `not_alive` | Eliminated participant cannot act |
| 413 | `body_too_large` | Body exceeds 32 KiB |
| 429 | `rate_limited` | Session request rate exceeded |
| 431 | `headers_too_large` | Headers exceed 16 KiB |
| 500 | `internal_error` | Unexpected server error |
| 503 | `server_full` | Server/lobby capacity reached |
