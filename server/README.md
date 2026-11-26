# NEON ARENA Server

The authoritative Python 3.10+ standard-library server for NEON ARENA. It owns the lobby, map generation, rules, five-mode settlement, strict turn deadlines, TCP Agent transport, HTTP JSON API, and JSONL match logs.

The server does **not** import or serve `client/` or `agents/`. It returns JSON only; `/`, `/client/*`, and unknown paths receive JSON `404`.

## Start

```powershell
Set-Location D:\NeonArena\server
python -m arena_server --host 0.0.0.0
```

Defaults:

- Agent/spectator TCP: `0.0.0.0:7777`, UTF-8 NDJSON, protocol `1`.
- Human/custom-client HTTP: `0.0.0.0:8080/api/v1`, JSON.
- Mode: `rotation`.
- Turn window: `15000` ms; minimum display time after all submit: `250` ms.
- Match: 2–4 players, 80 turns, 4 consecutive missed submissions forfeit.
- Lobby countdown: `5000` ms once the selected mode's minimum is met.
- Logs: `logs/` relative to the server's working directory.

```powershell
python -m arena_server --version
python -m arena_server --help
```

## Command-line configuration

| Argument | Default | Meaning |
| --- | --- | --- |
| `--host` | `0.0.0.0` | Bind address shared by TCP and HTTP |
| `--tcp-port` | `7777` | Agent and terminal-spectator port |
| `--api-port` | `8080` | HTTP JSON API port; `0` asks the OS for a port |
| `--tick-ms` | `15000` | Shared maximum decision window per turn |
| `--min-turn-ms` | `250` | Minimum delay after all living players submit |
| `--turn-limit` | `80` | Completed-turn limit |
| `--min-players` | `2` | Lobby minimum; must satisfy `2 <= min <= max <= 4` |
| `--max-players` | `4` | Maximum players taken into a match |
| `--lobby-wait-ms` | `5000` | Countdown after the selected mode's minimum is reached |
| `--max-missed-turns` | `4` | Consecutive missed/invalid submissions before forfeit |
| `--seed` | random | Base map seed; match index is added when configured |
| `--mode` | `rotation` | `rotation`, `classic`, `king`, `team`, `survival`, or `bounty` |
| `--log-dir` | `logs` | JSONL output directory |
| `--no-logs` | off | Disable match-file logging |
| `--cors-origin` | `*` | Allowed browser origin(s), comma-separated |
| `--max-clients` | `32` | Combined TCP connections and HTTP sessions |
| `--verbose` | off | Enable debug logging |
| `--version` | — | Print `Neon Arena 1.0.0` and exit |

`--mode team` requires `--max-players 4`; a team match itself requires exactly four players.

## Mode scheduling

Rotation order is `classic -> king -> team -> survival -> bounty`.

The server scans from the current cursor and chooses the first mode whose minimum is met by the waiting queue. `classic`, `king`, `survival`, and `bounty` require at least 2; `team` requires 4. The effective lobby minimum is `max(--min-players, mode minimum)`. With 2–3 waiting players, rotation skips team and advances past it. A fixed mode remains selected and does not advance the cursor.

```powershell
# Default rotation; two players see classic, king, survival, bounty in sequence
python -m arena_server --host 127.0.0.1 --mode rotation

# Fixed King of the Hill
python -m arena_server --host 127.0.0.1 --mode king

# Fixed Team 2v2; waits for four players
python -m arena_server --host 127.0.0.1 --mode team --max-players 4

# LLM-friendly decision windows (server terminal)
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 30000
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 60000

# LLM Agent terminal: raise the request cap to match the chosen server window
$env:NEON_ARENA_LLM_TIMEOUT_MS = "24000"  # use with --tick-ms 30000
$env:NEON_ARENA_LLM_TIMEOUT_MS = "48000"  # use instead with --tick-ms 60000
```

Lobby snapshots expose the actual next playable `mode`, `mode_label`, and `mode_description`, along with the effective `min_players`, `max_players`, players, and `starts_in_ms`.

## Match lifecycle

1. TCP `join` or HTTP `POST /sessions` enters one FIFO lobby.
2. The selected minimum starts a countdown; reaching `--max-players` starts immediately. Joining during the countdown does not reset it. Dropping below the minimum cancels it.
3. The server takes up to `--max-players` from the queue, assigns `P1`–`P4` in queue order, generates the map, and emits `start`.
4. Each turn emits `state` with the same absolute `reply_by_ms` deadline for every participant.
5. All living players submit, or the deadline expires. The server resolves one simultaneous turn, logs it, and emits the next state or `end`.
6. `end` includes `mode`, `mode_state`, final player standings, winner, and final events (or the immediate forfeit event when an out-of-turn forfeit ends the match). Team matches also include `team_standings` and a team winner.
7. Participants become idle. They are **not automatically re-queued**. TCP clients may send `join` again; HTTP clients may POST `/sessions` with the existing token to queue again.

Only one match runs at a time. Extra lobby members wait for the next match.

## Strict timing and late actions

`state.reply_by_ms` is an absolute Unix-millisecond deadline. `--tick-ms` is the longest shared window; `--min-turn-ms` is the shortest delay after every living player has submitted. There is no real-time movement, aiming, or private reaction window.

- A legal action may replace the same player's pending action while the turn is open.
- At or after `reply_by_ms`, `Match.submit` rejects the action with `turn_closed`; it is never applied to the closed turn.
- Missing or invalid actions resolve as `wait` and increment the missed-submission count. Four consecutive misses forfeit the player.
- TCP disconnect or explicit TCP `leave` forfeits immediately. HTTP `DELETE /sessions` forfeits immediately; merely closing an HTTP client does not, so the player can forfeit after missed turns.
- A forfeited team member is eliminated, but the match continues while either team has a living member.

The Agent SDK checks the deadline before and after policy execution. Late local actions are retained only in `expired_actions`. LLM requests are bounded to the smallest of `NEON_ARENA_LLM_TIMEOUT_MS`, 80% of `tick_ms`, and 90% of the remaining deadline, leaving time for fallback and submission.

## HTTP surface

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | No | Server/version/protocol/lobby/match counters |
| GET | `/api/v1/rules` | No | Rule numbers and public defaults, including `mode` |
| POST | `/api/v1/sessions` | Optional bearer | Create or recover a human session and queue |
| GET | `/api/v1/state` | Bearer | Poll lobby, current match, or frozen ended view |
| POST | `/api/v1/actions` | Bearer | Submit `{turn, action}` for the open turn |
| DELETE | `/api/v1/sessions` | Bearer | Leave/forfeit and invalidate the token |
| OPTIONS | Any request path | No | CORS preflight, `204` |

Every response uses `application/json; charset=utf-8`, `Content-Length`, and `Connection: close`. Success responses have `ok: true`; errors have `ok: false` and `error.code`/`error.message`.

HTTP limits and session behavior:

- Request headers: 16 KiB; request body: 32 KiB; request read timeout: 10 seconds.
- Chunked request bodies are rejected. An absent `Content-Length` means a zero-length body, not an error; a present value must be an ASCII non-negative decimal integer no greater than 32768.
- Per-session request rate: 20 requests per rolling second.
- Lobby sessions idle for more than 30 seconds without polling are removed.
- Ended views are retained for 600 seconds and can be re-queued with the same token.
- Default CORS origin is `*`; `--cors-origin` accepts a comma-separated allowlist. Error responses carry the same CORS policy.
- No cookies, account system, TLS, HTML, static files, or client proxy.

See [docs/HTTP_API.md](../docs/HTTP_API.md) and [docs/openapi.yaml](../docs/openapi.yaml).

## JSONL logs and replay

Unless `--no-logs` is set, each match writes one UTF-8 JSONL file under `--log-dir`:

```text
start  -> state (turn 1) -> state (turn 2) -> ... -> end
```

An out-of-turn forfeit may also emit an immediate `state` snapshot/log record. That record's `turn` and `events_turn` are the current open turn, and its `events` contain the forfeit rather than pretending a turn completed.

Every record includes `match_id`, `mode`, and `mode_state`. The file includes map seed/geometry, player snapshots, nodes, events, deadlines, final reason/winner/standings, and team standings where applicable. It contains no HTTP token or client IP.

From `agents/`:

```powershell
python -m tools.spectator --host 127.0.0.1 --port 7777 --once
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0.2 --plain
```

The spectator subscribes with `spectate`, does not occupy a player slot, and renders all mode events. Replay is offline and never opens a socket.

## Remote deployment

On a trusted LAN/VPN, allow inbound TCP `7777` and `8080` only. Do not expose raw TCP 7777 directly to an untrusted network or expose the separate client launcher's port `8090`. Clients and Agents connect outbound, so only the server needs inbound reachability.

```powershell
New-NetFirewallRule -DisplayName "NEON ARENA" -Direction Inbound -Protocol TCP -LocalPort 7777,8080 -Action Allow
```

The built-in server has no TLS and no user authentication beyond per-human bearer sessions. On untrusted networks, use a trusted LAN or VPN. An HTTP TLS reverse proxy protects only port 8080; it does **not** protect plaintext TCP 7777. Remote TCP Agents/spectators require a VPN, SSH tunnel/local forwarding, or a TLS wrapper that can carry raw TCP. Otherwise names, actions, tokens, and LLM-facing configuration are exposed to network observers. Restrict CORS to the deployed client origin and apply firewall/security-group allowlists where possible.

A browser loaded over HTTPS cannot call a plain HTTP API. Terminate TLS in front of the API or serve the client over a trusted HTTP origin.

## Tests

```powershell
Set-Location D:\NeonArena\server
python -m unittest discover -s tests -p "test_*.py" -v
```

The suite covers map generation, movement, combat, resources, endgame ordering, five modes, rotation, strict deadlines, TCP, HTTP, mixed transport, session recovery, JSONL logging, CORS, limits, and team results.

The root suite adds cross-process human + Agent matches for classic, king, and team modes, JSON-only HTTP checks, and PowerShell 5.1 script contracts:

```powershell
Set-Location D:\NeonArena
python -m unittest discover -s tests -v
```

PowerShell orchestration is available through `../scripts/start_server.ps1`, `demo.ps1`, and `play.ps1`; see the [root README](../README.md#powershell-scripts).
