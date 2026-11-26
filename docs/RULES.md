# NEON ARENA Rules

This document describes the shipped implementation. Numeric defaults come from `server/arena_server/config.py`; the authoritative per-match values are sent in `start.rules` and `GET /api/v1/rules`. The server alone validates actions and resolves outcomes.

## Match and arena

| Item | Value |
| --- | --- |
| Players | 2–4 per match; human and Agent may be mixed |
| Team mode | Exactly 4 players |
| Map | 15 x 15 cells; origin `[0,0]` is top-left |
| Walkable area | Interior `1..13` on both axes; the outer ring is impassable |
| Internal walls | 20 cells in 180-degree symmetric pairs when generation succeeds |
| Spawn points | `(1,1)`, `(13,13)`, `(13,1)`, `(1,13)` |
| Energy nodes | `(7,7)`, `(7,3)`, `(3,7)`, `(11,7)`, `(7,11)` |
| Default turn limit | 80 completed turns |
| Default decision window | 15000 ms per turn |
| Default minimum turn display | 250 ms after all living players submit |
| Default missed-turn limit | 4 consecutive turns |

Map generation protects the 3 x 3 neighborhoods of spawns and nodes, places walls in 180-degree pairs, and verifies that all spawns/nodes are connected. It retries up to 100 times and falls back to an interior with no internal walls if necessary. A configured seed makes map generation reproducible.

Two players receive one of two diagonal spawn pairs; three players receive three randomly chosen corners; four players receive all corners in shuffled order. Player IDs `P1`–`P4` follow lobby queue order.

## Player attributes

| Attribute | Initial | Maximum | Notes |
| --- | ---: | ---: | --- |
| HP | 100 | 100 | Zero HP eliminates the player |
| Energy | 40 | 100 | Spent on actions; regenerated for survivors |
| Shield | 0 | 40 | Absorbs attack damage before HP; does not decay |
| Score | 0 | — | Damage, kills, gathering, and mode objectives |
| Consecutive misses | 0 | — | Four missed/invalid turns forfeit |

## Actions

Each living player submits at most one effective action per turn. Directions are `n` (north), `e` (east), `s` (south), and `w` (west).

| Action | JSON | Energy cost | Submission requirements | Effect |
| --- | --- | ---: | --- | --- |
| Move | `{"type":"move","dir":"n"}` | 0 | Valid direction; adjacent target walkable | Move 1 cell unless simultaneous collision blocks it |
| Dash | `{"type":"dash","dir":"n"}` | 18 | Valid direction; middle and target walkable; enough energy | Move 2 cells; cost is paid even if blocked |
| Attack | `{"type":"attack","dir":"n"}` | 8 | Valid direction; enough energy | Attack the adjacent cell after movement; may miss |
| Gather | `{"type":"gather"}` | 0 | Standing on an active node | +30 energy (capped), +10 score, node cooldown 4 |
| Shield | `{"type":"shield"}` | 12 | Shield below 40; enough energy | +26 shield (capped at 40) |
| Heal | `{"type":"heal"}` | 25 | HP below 100; enough energy | +25 HP (capped at 100) |
| Wait | `{"type":"wait"}` | 0 | Always legal for a living player | No direct effect; counts as a valid submission |

Unknown action types/directions are rejected. Extra fields are ignored. Rejected submissions do not spend resources and may be corrected during the same open turn.

`move` and `dash` validate walls/bounds at submission, but occupancy and multi-player collisions are resolved simultaneously. The current engine reports `wall` for both border and internal-wall movement failures.

## Turn timing

1. The server broadcasts the full `state` and absolute `reply_by_ms` deadline.
2. Every living player shares the same `tick_ms` window. A new legal submission replaces that player's pending action while the turn remains open.
3. If every living player submits, resolution waits until `min_turn_ms`; otherwise resolution occurs at the deadline.
4. The server closes the turn and resolves all actions together.

There is no real-time movement, continuous fire, reaction-speed test, or private deadline extension. At or after the deadline, the server returns `turn_closed`; a late Agent action is not applied retroactively. Missing/invalid actions become `wait` for resolution and increment the miss count. A valid action resets the count, even if its movement is blocked or its attack misses.

For LLM Agents, use `--tick-ms 30000` or `--tick-ms 60000` and raise `NEON_ARENA_LLM_TIMEOUT_MS` in the Agent environment to `24000` or `48000`, respectively. The bundled LLM policy limits a request to the smallest of that configured timeout, 80% of `tick_ms`, and 90% of the remaining deadline, then falls back or waits if it cannot produce a timely legal action.

## Simultaneous resolution order

The engine performs these phases in order:

1. **Choose actions.** Canonical, affordable actions are accepted; other actions become `wait`. Accepted actions reset the player's miss count; misses increment it.
2. **Spend energy.** Dash, attack, heal, and shield costs are deducted. If a cost can no longer be paid, the action degrades to `wait` and counts as missed.
3. **Move simultaneously.** Positions come from turn start. Targets must be walkable, initially empty, and unique. A dash also needs an empty walkable middle cell that is not another mover's target. Conflicting moves emit `blocked` with reason `occupied` or `collision`. Players cannot swap or pass through one another.
4. **Apply non-movement effects.** Shield, heal, and gather occur before combat and can affect the same turn's incoming attack.
5. **Attack simultaneously.** Attacks use post-movement positions. All attacks land even if the attacker also receives lethal damage. Shield absorbs up to 22 damage first; only actual HP loss deals damage score. Friendly-fire blocks in team mode still consume attack energy.
6. **Resolve deaths and kill credit.** HP zero eliminates a player. The attacker with the most actual HP damage this turn gets the kill; ties go to the lowest player ID. Kill rewards are mode-dependent.
7. **Apply mode death hooks.** Survival may shrink the zone and deal storm damage on shrink turns; bounty marks target damage and emits completion events.
8. **Regenerate energy and cool nodes.** Players alive at the end of combat/storm gain 4 energy up to 100. Every node with cooldown above zero decreases by 1.
9. **Apply missed-turn forfeits.** A living, non-forfeited player with 4 consecutive misses becomes `alive=false`, `hp=0`, `forfeited=true`, with a `forfeit` event and no killer.
10. **Apply mode end-of-turn hooks.** King hill scoring, team aggregate refresh, and bounty retargeting occur here.
11. **Check victory.** The first matching condition below sets `end.reason`; otherwise the turn increments.

## Damage, kills, and score

Base values apply in every mode unless a mode changes them:

| Source | Score |
| --- | ---: |
| Actual HP damage | 1 per point |
| Shield damage | 0 |
| Ordinary kill | +25 |
| Gathering | +10 |

`damage_dealt` always records actual HP damage, independent of score multipliers. Overkill scores only the target's remaining HP.

## Victory and ranking

End conditions are checked in this exact order:

1. One living **unit** remains: `last_standing`.
2. Zero living units remain: `mutual_destruction`.
3. A mode score limit is reached: `score_limit`.
4. The completed-turn limit is reached: `turn_limit`.

A unit is a player except in team mode, where it is a team with at least one living member. An unexpected server failure can produce `aborted`, which has no winner.

Player standings sort by:

1. Alive first.
2. Higher score.
3. Higher HP.
4. Higher energy.
5. Lower player ID.

For `last_standing`, the survivor wins. For `mutual_destruction`, `turn_limit`, and `score_limit`, the mode's top-ranked player/team wins. Team standings sort by living members, total score, total HP, total energy, then team ID.

## Lobby and mode selection

The server runs one match at a time. The effective lobby minimum is the larger of `--min-players` and the selected mode's minimum. Once met, a default 5000 ms countdown starts; reaching `--max-players` starts immediately. New joins do not reset the countdown, and dropping below the minimum cancels it.

Default mode order:

```text
classic -> king -> team -> survival -> bounty -> classic
```

Rotation scans from its cursor and selects the first playable mode. With 2–3 waiting players, `team` is skipped and the cursor advances past it. With 4 players it is eligible. Fixed `--mode` selection does not rotate.

| Mode | Minimum | `mode_state` | Player additions |
| --- | ---: | --- | --- |
| `classic` | 2 | `{}` | None |
| `king` | 2 | `zone`, `target_score`, `streaks` | `hill_streak` |
| `team` | 4 | `teams` | `team` |
| `survival` | 2 | `zone`, `next_shrink_turn`, `storm_damage` | `in_storm` |
| `bounty` | 2 | `target_score`, `targets` | `bounty_target`, `bounty_streak` |

## Classic

Classic preserves the base rules: last survivor, mutual destruction, or turn-limit ranking. It has no mode-specific events and `mode_state` is `{}`.

## King of the Hill

- Zone: center 3 x 3, `x` and `y` both in `6..8` inclusive.
- After combat, regen, cooldown, and forfeits, each living player in the zone scores `5 + min(previous_streak, 5)`.
- The streak bonus itself is capped at 5, so the total hill award is capped at 10 points per turn.
- Streak points by consecutive turn are `5, 6, 7, 8, 9, 10, 10, ...`.
- Leaving the zone, dying, or forfeiting resets that player's streak to 0.
- Any player reaching 100 score ends the match with `score_limit`.
- Event: `hill_score` contains `player`, `pos`, `points`, `streak`, and resulting `score`.

```json
{
  "zone": {"min": [6, 6], "max": [8, 8]},
  "target_score": 100,
  "streaks": {"P1": 2, "P2": 0}
}
```

## Team 2v2

- Exactly four players start.
- `P1/P2` are `T1` / Team A; `P3/P4` are `T2` / Team B.
- Team score is the sum of member scores; `alive` is the number of living members.
- Friendly attacks are blocked: they spend energy but cause no HP/shield loss, damage score, or kill credit, and emit `friendly_blocked`.
- A team is eliminated when both members are dead. The other team wins by `last_standing`.
- If both teams are eliminated, `mutual_destruction` still selects the top team by team standings.
- Team result fields include `winner.kind="team"`, `winner.members`, and `team_standings` with `id`, `name`, `members`, `score`, `alive`, `hp`, and `energy`.

```json
{
  "teams": [
    {"id": "T1", "name": "Team A", "members": ["P1", "P2"], "score": 30, "alive": 2},
    {"id": "T2", "name": "Team B", "members": ["P3", "P4"], "score": 18, "alive": 1}
  ]
}
```

## Survival

- Initial safe zone: `[1,1]..[13,13]`.
- After completed turns 6, 12, 18, 24, and 30, each zone edge moves inward by 1, never smaller than `[6,6]..[8,8]`.
- Immediately after each shrink, every living player outside the new zone takes 12 true HP damage.
- Storm damage ignores shield, gives no damage score, and has no killer. A lethal storm hit emits `death` with `killer: null`.
- Storm damage occurs **only on shrink turns**, not after every ordinary turn.
- `next_shrink_turn` becomes `null` after the turn-30 shrink.

| Completed turn | Safe zone |
| ---: | --- |
| Initial | `[1,1]..[13,13]` |
| 6 | `[2,2]..[12,12]` |
| 12 | `[3,3]..[11,11]` |
| 18 | `[4,4]..[10,10]` |
| 24 | `[5,5]..[9,9]` |
| 30 and later | `[6,6]..[8,8]` |

Events: `storm_shrink` contains the new `zone` and nullable `next_shrink_turn`; `storm_damage` contains `player`, `amount`, and resulting `hp`.

```json
{
  "zone": {"min": [2, 2], "max": [12, 12]},
  "next_shrink_turn": 12,
  "storm_damage": 12
}
```

## Bounty

- Initial targets cycle by player ID: `P1 -> P2`, `P2 -> P3`, `P3 -> P4`, `P4 -> P1`.
- Every player has one public target. Dead players have `bounty_target: null` and streak 0.
- Damage to the current target doubles damage **score**, not the 22-point HP damage or `damage_dealt`.
- Killing the current target awards `25 base + 25 bounty + min(previous_streak, 3) * 5`: 50, 55, 60, then 65 on subsequent target kills.
- Killing a non-target awards the ordinary 25 and does not increase bounty streak.
- Any player reaching 150 score ends the match with `score_limit`.
- After turn resolution, living players are retargeted to the next living player in ID cycle. Explicit forfeits update targets in state immediately but do not append retarget events.
- A target-damage event adds `bounty: true`. Target kills append `bounty_complete`; resolution retargets append `bounty_retarget`.

```json
{
  "target_score": 150,
  "targets": {"P1": "P2", "P2": "P3", "P3": "P4", "P4": "P1"}
}
```

## Node cooldown

Gathering sets `cooldown=4`; the same turn's cooldown phase reduces it to 3. It then reaches 0 after three further completed turns. A node is active exactly when `cooldown == 0`. Node state is public; there is no fog of war.

## Forfeit, disconnect, and end-of-match behavior

- TCP disconnect or `leave`: immediate forfeit (`alive=false`, `hp=0`, `stats.forfeited=true`, no killer), then detach from the match with no further old-match messages. Remaining players continue if the mode is not over.
- HTTP `DELETE /sessions`: immediate forfeit and detach with no further old-match messages, then token invalidation.
- Closing only the HTTP client/page: no immediate forfeit; missed turns eventually eliminate the player.
- Four consecutive missed/invalid turns: forfeit at the missed-turn phase.
- An out-of-turn forfeit may emit an immediate `state` snapshot and JSONL record to remaining participants/spectators. Its `turn` and `events_turn` are the current open turn, and its `events` contain the forfeit; this does not increment the completed-turn count. If the forfeit ends the match, `end.turns` remains the completed-turn count while `end.events_turn` identifies the forfeit turn.
- Dead or forfeited participants who remain attached (for example, after missed-turn forfeits) cannot act but continue receiving snapshots until `end`. Explicit `leave`, TCP disconnect, and HTTP `DELETE /sessions` detach the participant, which receives no further old-match messages.
- After `end`, all participants are idle. Nothing automatically rejoins the lobby. TCP clients must send `join` again; HTTP clients must POST `/sessions` again with their token.
