"""Policy interface and shared local action-legality helpers."""

from __future__ import annotations

from .protocol import DIRS


class Policy:
    """Base class for turn-based agent policies."""

    def on_lobby(self, lobby):
        return None

    def on_start(self, start):
        return None

    def decide(self, state):
        return {"type": "wait"}

    def on_end(self, end):
        return None

    def on_error(self, error):
        return None


def safe_decide(policy: Policy, state):
    """Keep a broken policy from crashing the client connection."""
    try:
        return policy.decide(state)
    except Exception as exc:
        print(f"policy error: {type(exc).__name__}")
        return {"type": "wait"}


def position(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x, y = value
    if (not isinstance(x, int) or isinstance(x, bool)
            or not isinstance(y, int) or isinstance(y, bool)):
        return None
    return x, y


def find_player(state, player_id):
    for player in state.get("players", []):
        if isinstance(player, dict) and player.get("id") == player_id:
            return player
    return None


def node_at(state, pos):
    for node in state.get("nodes", []):
        if isinstance(node, dict) and position(node.get("pos")) == pos:
            return node
    return None


def node_is_active(node):
    if not isinstance(node, dict):
        return False
    cooldown = node.get("cooldown", 0)
    return (isinstance(cooldown, int) and not isinstance(cooldown, bool)
            and cooldown == 0 and node.get("active", True) is not False)


def arena_geometry(start):
    arena = start.get("arena") or {}
    width = arena.get("width", 15)
    height = arena.get("height", 15)
    if not isinstance(width, int) or width <= 0:
        width = 15
    if not isinstance(height, int) or height <= 0:
        height = 15
    walls = set()
    for wall in arena.get("walls", []):
        pos = position(wall)
        if pos is not None:
            walls.add(pos)
    return width, height, walls


def rule_value(rules, name, default):
    value = rules.get(name, default)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def action_cost(rules, name, default):
    value = (rules.get(name) or {}).get("cost", default)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def legal_actions(start, state, player_id):
    """Collect actions that are locally valid against the visible snapshot."""
    me = find_player(state, player_id)
    pos = position(me.get("pos")) if me else None
    if me is None or pos is None or not me.get("alive", False):
        return []
    rules = start.get("rules") or {}
    width, height, walls = arena_geometry(start)
    energy = me.get("energy", 0)
    occupied = set()
    for other in state.get("players", []):
        if not isinstance(other, dict) or other.get("id") == player_id:
            continue
        other_pos = position(other.get("pos"))
        if other.get("alive", False) and other_pos is not None:
            occupied.add(other_pos)

    def walkable(target):
        x, y = target
        return (0 < x < width - 1 and 0 < y < height - 1
                and target not in walls)

    actions = [{"type": "wait"}]
    for direction, (dx, dy) in DIRS.items():
        target = (pos[0] + dx, pos[1] + dy)
        if walkable(target) and target not in occupied:
            actions.append({"type": "move", "dir": direction})

    dash_cost = action_cost(rules, "dash", 18)
    dash_distance = rule_value(rules.get("dash") or {}, "distance", 2)
    if energy >= dash_cost:
        for direction, (dx, dy) in DIRS.items():
            middle = (pos[0] + dx, pos[1] + dy)
            target = (pos[0] + dx * dash_distance, pos[1] + dy * dash_distance)
            if (walkable(middle) and walkable(target)
                    and middle not in occupied and target not in occupied):
                actions.append({"type": "dash", "dir": direction})

    if energy >= action_cost(rules, "attack", 8):
        actions.extend({"type": "attack", "dir": direction}
                       for direction in DIRS)

    node = node_at(state, pos)
    if node_is_active(node):
        actions.append({"type": "gather"})

    max_hp = rule_value(rules, "max_hp", 100)
    if me.get("hp", 0) < max_hp and energy >= action_cost(rules, "heal", 25):
        actions.append({"type": "heal"})

    max_shield = rule_value((rules.get("shield") or {}), "max", 40)
    if (me.get("shield", 0) < max_shield
            and energy >= action_cost(rules, "shield", 12)):
        actions.append({"type": "shield"})
    return actions


__all__ = [
    "Policy", "safe_decide", "position", "find_player", "node_at",
    "node_is_active", "arena_geometry", "legal_actions", "action_cost",
    "rule_value",
]
