# NEON ARENA Agent SDK

Python 3.10+ standard-library-only TCP agents, bots, and terminal spectator.
Run commands from this `agents/` directory so `arena_agent`, `bots`, and `tools`
are importable. The authoritative server lives in `../server`.

## TCP protocol

The server sends and accepts one UTF-8 JSON object per line (NDJSON), protocol
version `1`. `arena_agent.protocol` provides `PROTOCOL`, `DIRS`, `encode`, and
`decode`. A client receives `welcome`, sends `join`, then receives `lobby`,
`start`, and per-turn `state` messages. Actions use the state's current turn:

```json
{"type":"action","turn":1,"action":{"type":"move","dir":"e"}}
```

`start` contains rules, arena geometry, player identities, `mode`, `mode_state`,
and `tick_ms`. `state` contains visible players/nodes/events, mode fields, and an
absolute `reply_by_ms` deadline. `end` contains the reason and rankings.

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

`Policy` callbacks are `on_lobby`, `on_start`, `decide`, `on_end`, and
`on_error`. `safe_decide` converts policy exceptions to `wait`. `ArenaClient`
validates the welcome, retries connection failures with 1/2/4/8-second backoff,
and exits after a match unless `requeue=True`. `run_agent` is a convenience
wrapper.

`bfs_next_step(start, goal, walls, occupied)` returns the first cardinal step on
a shortest four-neighbor path, or `None`. `adjacent_dir(a, b)` returns a
direction only for orthogonally adjacent coordinates.

## Bots

```bash
python -m bots.random_bot --host 127.0.0.1 --port 7777 --name Random --quiet
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha --strategy balanced
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Beta --strategy aggressive --seed 7
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Collector --strategy collector
```

The random bot seeds `random.Random` with `zlib.crc32(name)` rather than Python's
process-randomized `hash()`. Both non-LLM bots build actions from the visible
snapshot and check walls, occupants, energy, HP/shield limits, and node cooldown
before submitting.

Heuristic strategies use different healing thresholds and target preferences:

- `aggressive`: heals at HP 55 or below and hunts enemies first.
- `balanced`: heals at HP 35 or below and chooses the nearest node/enemy approach.
- `collector`: heals at HP 45 or below, prefers active nodes, and only attacks
  adjacent enemies below HP 50.

Mode objectives override ordinary target choice: survival moves toward the
nearest safe-zone cell while `in_storm`; king moves toward the center zone; team
excludes same-team players from enemy targets; bounty approaches its assigned
`bounty_target` first and falls back to other living enemies if necessary.

## LLM bot and decision deadlines

```bash
export NEON_ARENA_LLM_BASE_URL=http://127.0.0.1:11434/v1
export NEON_ARENA_LLM_MODEL=your-model
export NEON_ARENA_LLM_API_KEY=optional-key
export NEON_ARENA_LLM_TIMEOUT_MS=20000
python -m bots.llm_agent --host 127.0.0.1 --port 7777 --name LLM
```

The endpoint must be OpenAI-compatible at `<base_url>/chat/completions`. The
prompt includes rules, the local player, enemies, nodes, recent events,
`mode`, `mode_state`, and a mode explanation. Parsing failures, HTTP errors, and
timeouts use the heuristic fallback; `--no-fallback` returns `wait` instead.
API keys are sent only in the Authorization header and are never logged.

LLM matches must use a longer server decision window:

```bash
cd ../server
python -m arena_server --host 127.0.0.1 --tick-ms 30000 --mode rotation
# or --tick-ms 60000 for slower models/endpoints
```

Every player shares the same turn window; there is no real-time control. The
LLM request budget is capped at 80% of the server's `tick_ms` (and at the
remaining time before `reply_by_ms`) to leave time for fallback and submission.
The client checks the deadline again after `decide`. Any action produced at or
after the deadline is recorded only in `expired_actions` and is not submitted or
retried on a later turn.

## Spectator and replay

```bash
python -m tools.spectator --host 127.0.0.1 --port 7777 --once
python -m tools.spectator --host 127.0.0.1 --port 7777 --plain
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0.2 --plain
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0 --no-color
```

Live mode clears the terminal by default (`cls` on Windows, `clear` elsewhere).
`--plain` disables clearing and ANSI color; `--no-color` disables only color.
`--once` exits after the first match, while the default follows later matches.
Replay reads start/state/end JSONL records without connecting to a server;
`--delay 0` emits every frame immediately.

The renderer shows walls, players, active/cooling nodes, turn and player status,
the mode title/zone text, and readable event summaries. King hill scores, storm
shrink/damage, bounty completion/retargeting, friendly-fire blocks, and unknown
future event types are rendered without crashing.

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite covers protocol validation, BFS, client callbacks/retries/deadlines,
renderer and replay behavior, deterministic random actions, all mode-aware
heuristic objectives, LLM parsing/prompts/configuration/fallback, and strict LLM
turn expiry.
