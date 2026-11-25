"""ASCII board and event rendering shared by agents and spectators."""

from __future__ import annotations

import json

from .policy import arena_geometry, find_player, node_is_active, position

MODE_LABELS = {
    "classic": "Classic", "king": "King of the Hill", "team": "Team 2v2",
    "survival": "Survival", "bounty": "Bounty",
}


def summarize_event(event):
    """Return a readable one-line summary, including for future event types."""
    if not isinstance(event, dict):
        return f"Event: {event}"
    kind = event.get("type", "unknown")
    player = event.get("player", "?")
    if kind == "hill_score":
        return (f"Hill score: {player} +{event.get('points', 0)} "
                f"(streak {event.get('streak', 0)})")
    if kind == "storm_shrink":
        return f"Storm shrink: zone={event.get('zone')} next={event.get('next_shrink_turn')}"
    if kind == "storm_damage":
        return f"Storm damage: {player} -{event.get('amount', 0)} HP"
    if kind == "bounty_complete":
        return (f"Bounty complete: {player} eliminated {event.get('target')} "
                f"for +{event.get('bonus', 0)}")
    if kind == "bounty_retarget":
        return f"Bounty retarget: {player} -> {event.get('target')}"
    if kind == "friendly_blocked":
        return f"Friendly fire blocked: {player} -> {event.get('target')}"
    if kind in ("move", "dash"):
        return f"{kind.title()}: {player} {event.get('from')} -> {event.get('to')}"
    if kind == "attack":
        return f"Attack: {player} {event.get('dir')} target={event.get('target')}"
    if kind == "damage":
        return (f"Damage: {event.get('player')} -> {event.get('target')} "
                f"HP -{event.get('hp_damage', 0)} shield -{event.get('shield_damage', 0)}")
    if kind in ("heal", "shield", "gather"):
        return f"{kind.title()}: {player} {json.dumps(event, ensure_ascii=False, default=str)}"
    if kind == "death":
        return f"Death: {player} killer={event.get('killer')}"
    if kind == "blocked":
        return f"Blocked: {player} {event.get('action')} {event.get('dir')} ({event.get('reason')})"
    if kind == "forfeit":
        return f"Forfeit: {player}"
    try:
        detail = json.dumps(event, ensure_ascii=False, separators=(",", ":"),
                            default=str)
    except (TypeError, ValueError, RecursionError):
        detail = str(event)
    return f"Event {kind}: {detail}"


def _zone_text(mode_state):
    if not isinstance(mode_state, dict):
        return "zone=unavailable"
    zone = mode_state.get("zone")
    if not isinstance(zone, dict):
        return "zone=unavailable"
    low, high = zone.get("min"), zone.get("max")
    if (not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple))
            or len(low) != 2 or len(high) != 2):
        return "zone=unavailable"
    return f"zone=[{low[0]},{low[1]}]-[{high[0]},{high[1]}]"


def _paint(text, code, color):
    return f"\x1b[{code}m{text}\x1b[0m" if color else text


def render_board(start, state, color=True) -> str:
    """Render a complete board plus mode/status/event text without raising."""
    start = start if isinstance(start, dict) else {}
    state = state if isinstance(state, dict) else {}
    width, height, walls = arena_geometry(start)
    grid = [["." for _ in range(width)] for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if x in (0, width - 1) or y in (0, height - 1) or (x, y) in walls:
                grid[y][x] = _paint("#", "90", color)
    for node in state.get("nodes", []):
        if not isinstance(node, dict):
            continue
        pos = position(node.get("pos"))
        if pos is None or not (0 <= pos[0] < width and 0 <= pos[1] < height):
            continue
        symbol = "*" if node_is_active(node) else "o"
        grid[pos[1]][pos[0]] = _paint(symbol, "33", color)

    players = [player for player in state.get("players", [])
               if isinstance(player, dict) and position(player.get("pos")) is not None]
    initials = {}
    for player in players:
        name = str(player.get("name") or player.get("id") or "?")
        initial = name[0]
        initials[initial] = initials.get(initial, 0) + 1
    for player in players:
        pos = position(player.get("pos"))
        if not (0 <= pos[0] < width and 0 <= pos[1] < height):
            continue
        name = str(player.get("name") or player.get("id") or "?")
        symbol = name[0]
        if initials[name[0]] > 1:
            symbol = str(player.get("id") or symbol)
        grid[pos[1]][pos[0]] = _paint(symbol, "96", color)

    mode = str(state.get("mode") or start.get("mode") or "classic")
    mode_state = state.get("mode_state", start.get("mode_state", {}))
    title = f"NEON ARENA | {MODE_LABELS.get(mode, mode)} [{mode}]"
    you = state.get("you")
    me = find_player(state, you) if you else (players[0] if players else None)
    if me is None:
        status = "Turn ? | no player view"
    else:
        status = (f"Turn {state.get('turn', '?')}/{state.get('turn_limit', '?')} | "
                  f"You {me.get('id', '?')} HP {me.get('hp', 0)} "
                  f"Energy {me.get('energy', 0)} Shield {me.get('shield', 0)} "
                  f"Score {me.get('score', 0)}")
    mode_bits = [_zone_text(mode_state)]
    if isinstance(mode_state, dict):
        for key in ("next_shrink_turn", "storm_damage", "target_score"):
            if key in mode_state:
                mode_bits.append(f"{key}={mode_state[key]}")
    if isinstance(me, dict):
        for key in ("team", "bounty_target", "in_storm", "hill_streak",
                    "bounty_streak"):
            if key in me:
                mode_bits.append(f"{key}={me[key]}")
    lines = [title]
    lines.extend("".join(row) for row in grid)
    lines.extend(["", status, "Mode: " + " ".join(mode_bits)])
    events = state.get("events", [])
    if isinstance(events, list) and events:
        lines.append("Events:")
        lines.extend("  " + summarize_event(event) for event in events)
    return "\n".join(lines)


__all__ = ["render_board", "summarize_event", "MODE_LABELS"]
