# NEON ARENA Agent SDK

Python 3.10+ standard-library-only TCP Agents, bots, and terminal spectator/replay tools.

Run commands from this `agents/` directory so `arena_agent`, `bots`, and `tools` are importable. This product is independently deployable and does not import `server/` or `client/`.

## Connect to the five-mode server

The server defaults to rotation: `classic -> king -> team -> survival -> bounty`. Rotation skips `team` with 2–3 waiting players; fixed team mode requires exactly four. All modes use the same TCP protocol version `1` and the same seven actions.

The server sends and accepts one UTF-8 JSON object per line (NDJSON):

```json
{"type":"action","turn":1,"action":{"type":"move","dir":"e"}}
```

A client receives `welcome`, sends `join`, then receives `joined`, `lobby`, `start`, and per-turn `state` messages. `start` contains rules, arena geometry, player identities, `mode`, `mode_state`, `tick_ms`, and `min_turn_ms`. `state` contains visible players/nodes/events, mode fields, and an absolute `reply_by_ms` deadline. `end` contains `mode`, `mode_state`, reason, winner, standings, and final events; team matches add `team_standings` and a team winner. An out-of-turn forfeit may produce an immediate `state` snapshot/log record with `turn` and `events_turn` equal to the current open turn.

The full contract is in [docs/PROTOCOL.md](../docs/PROTOCOL.md).

## SDK

```python
from arena_agent import ArenaClient, Policy

class MyPolicy(Policy):
    def on_start(self, start):
        self.start = start

    def decide(self, state):
        me = next(p for p in state["players"] if p["id"] == state["you"])
        if me["hp"] <= 30:
            return {"type": "heal"}
        return {"type": "wait"}

client = ArenaClient("127.0.0.1", 7777, "MyAgent", MyPolicy())
client.run()
```

`Policy` callbacks are `on_lobby`, `on_start`, `decide`, `on_end`, and `on_error`. `safe_decide` converts policy exceptions to `wait`. `ArenaClient` validates the welcome, retries connection failures with 1/2/4/8-second backoff, and exits after a match unless `requeue=True`. `run_agent` is a convenience wrapper. The bundled bot CLIs do not expose a requeue flag; restart them or use the SDK option for continuous play.

`legal_actions(start, state, player_id)` filters actions using the visible snapshot and server-provided rules. `bfs_next_step(start, goal, walls, occupied)` returns the first cardinal step on a shortest four-neighbor path, or `None`. `bfs_next_step_to_any` accepts multiple goals. `adjacent_dir(a, b)` returns a direction only for orthogonally adjacent coordinates.

## Bots

```powershell
python -m bots.random_bot --host 127.0.0.1 --port 7777 --name Random --quiet
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha --strategy balanced
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Beta --strategy aggressive --seed 7
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Collector --strategy collector
```

All non-LLM bots build actions from the visible snapshot and check walls, occupants, energy, HP/shield limits, and node cooldown before submitting.

### Random bot

`RandomPolicy` chooses uniformly from locally legal actions. It seeds `random.Random` with `zlib.crc32(name)` rather than Python's process-randomized `hash()`. It remains mode-agnostic: it does not pursue hill, storm, team, or bounty objectives, but its legal actions work in all five modes.

### Heuristic bot

Heuristic strategies use different healing thresholds and target preferences:

| Strategy | Heal threshold | Ordinary target preference |
| --- | ---: | --- |
| `aggressive` | HP <= 55 | Enemies before active nodes |
| `balanced` | HP <= 35 | Nearest active node or enemy approach |
| `collector` | HP <= 45 | Active nodes first; attacks adjacent enemies below HP 50 |

Mode objectives override ordinary targeting:

- `classic`: ordinary strategy behavior.
- `king`: after combat/resource priorities, move toward the center `[6,6]..[8,8]`; stay in the zone to build `hill_streak`.
- `team`: exclude players with the same `team` from enemy selection; only enemies are attacked or approached.
- `survival`: if `in_storm` is true, escaping to the nearest cell inside `mode_state.zone` takes precedence over every other goal.
- `bounty`: approach or attack the assigned `bounty_target` before generic enemies; if unavailable, fall back to living enemies.

The policy reads current `state.mode_state` for changing zone/target data and `start.rules` for costs and limits. The server remains authoritative even when local legality checks succeed.

## LLM bot and strict decision deadlines

PowerShell 5.1 environment setup:

```powershell
$env:NEON_ARENA_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:NEON_ARENA_LLM_MODEL = "neon-arena"
$env:NEON_ARENA_LLM_API_KEY = "optional-key"
$env:NEON_ARENA_LLM_TIMEOUT_MS = "20000"
python -m bots.llm_agent --host 127.0.0.1 --port 7777 --name LLM
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEON_ARENA_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible base URL |
| `NEON_ARENA_LLM_MODEL` | `neon-arena` | Model name sent to `/chat/completions` |
| `NEON_ARENA_LLM_API_KEY` | unset | Optional Bearer credential |
| `NEON_ARENA_LLM_TIMEOUT_MS` | `20000` | Per-request cap before server-window caps |

The endpoint must implement `<base_url>/chat/completions`. The prompt includes rules, arena geometry, exact locally legal actions, the local player, other players, nodes, recent events, `mode`, a mode explanation, and `mode_state`. It states that all players share one decision window and asks for exactly one action object.

The LLM bot uses only `urllib.request`; no LLM SDK is bundled or required. An actual model endpoint is optional and external to the zero-dependency game runtime. API keys are sent only in the Authorization header and are never logged.

Start the server with a larger shared window for LLM play:

```powershell
# Server terminal
Set-Location D:\NeonArena\server
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 30000
# Server terminal: slower models/endpoints
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 60000

# LLM Agent terminal: raise the request cap to match the chosen server window
$env:NEON_ARENA_LLM_TIMEOUT_MS = "24000"  # use with --tick-ms 30000
$env:NEON_ARENA_LLM_TIMEOUT_MS = "48000"  # use instead with --tick-ms 60000
```

Every player receives the same `reply_by_ms` deadline. There is no real-time control and no per-Agent extension. The LLM request budget is the smaller of 80% of `tick_ms`, the configured timeout, and 90% of the remaining deadline. Parsing failures, illegal model actions, HTTP errors, and timeouts use the mode-aware heuristic fallback. `--no-fallback` returns `wait` instead.

The client checks the deadline before and after `decide`. Any action produced at or after the deadline is recorded only in `expired_actions` with reason `turn_deadline_passed`; it is not submitted or retried on a later turn. The server independently rejects late submissions with `turn_closed`, so late actions never affect an already resolved turn.

## Spectator and replay

```powershell
python -m tools.spectator --host 127.0.0.1 --port 7777 --once
python -m tools.spectator --host 127.0.0.1 --port 7777 --plain
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0.2 --plain
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0 --no-color
```

Live mode clears the terminal by default (`cls` on Windows, `clear` elsewhere). `--plain` disables clearing and ANSI color; `--no-color` disables only color. `--once` exits after the first match, while the default follows later matches. Replay reads `start`/`state`/`end` JSONL records without connecting to a server; `--delay 0` emits every frame immediately.

The renderer shows walls, players, active/cooling nodes, turn/player status, the mode title/zone text, and readable event summaries. King hill scores, storm shrink/damage, bounty completion/retargeting, friendly-fire blocks, team fields, and unknown future event types are rendered without crashing.

## Tests

```powershell
Set-Location D:\NeonArena\agents
python -m unittest discover -s tests -v
```

The suite covers protocol validation, BFS, client callbacks/retries/deadlines, renderer and replay behavior, deterministic random actions, all mode-aware heuristic objectives, LLM parsing/prompts/configuration/fallback, and strict LLM turn expiry.
