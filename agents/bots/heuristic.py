"""Mode-aware heuristic bot with local action validation."""

from __future__ import annotations

import argparse
import random

from arena_agent.client import run_agent
from arena_agent.pathfinding import adjacent_dir, bfs_next_step_to_any
from arena_agent.policy import (
    Policy, action_cost, arena_geometry, find_player, legal_actions, node_at,
    node_is_active, position,
)
from arena_agent.protocol import DIRS


class HeuristicPolicy(Policy):
    """A transparent target-selection policy for all five game modes."""

    HEAL_THRESHOLDS = {"aggressive": 55, "collector": 45, "balanced": 35}
    STRATEGIES = ("aggressive", "collector", "balanced")

    def __init__(self, strategy="balanced", seed=None):
        if strategy not in self.STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}")
        self.strategy = strategy
        self.rng = random.Random(seed)
        self.start_payload = {}
        self.mode = "classic"
        self.mode_state = {}
        self.player_id = None
        self.rules = {}

    def on_start(self, start):
        self.start_payload = start
        self.mode = start.get("mode", "classic")
        self.mode_state = start.get("mode_state") or {}
        self.player_id = start.get("you")
        self.rules = start.get("rules") or {}

    def _geometry(self):
        width, height, walls = arena_geometry(self.start_payload)
        # The authoritative engine treats the outer ring as impassable even
        # though it is not included in arena.walls.
        walls = set(walls)
        for x in range(width):
            walls.add((x, 0))
            walls.add((x, height - 1))
        for y in range(height):
            walls.add((0, y))
            walls.add((width - 1, y))
        return width, height, walls

    @staticmethod
    def _zone_bounds(mode_state, default):
        zone = mode_state.get("zone")
        if not isinstance(zone, dict):
            return default
        low, high = zone.get("min"), zone.get("max")
        if not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple)):
            return default
        if len(low) != 2 or len(high) != 2:
            return default
        if not all(isinstance(value, int) and not isinstance(value, bool)
                   for value in (*low, *high)):
            return default
        return low, high

    @staticmethod
    def _inside(pos, bounds):
        (min_x, min_y), (max_x, max_y) = bounds
        return min_x <= pos[0] <= max_x and min_y <= pos[1] <= max_y

    @staticmethod
    def _zone_cells(bounds, width, height):
        (min_x, min_y), (max_x, max_y) = bounds
        return {
            (x, y)
            for x in range(max(1, min_x), min(width - 1, max_x) + 1)
            for y in range(max(1, min_y), min(height - 1, max_y) + 1)
        }

    def _enemies(self, me, snapshot):
        enemies = []
        my_team = me.get("team")
        for other in snapshot.get("players", []):
            if not isinstance(other, dict) or other.get("id") == me.get("id"):
                continue
            if not other.get("alive", False) or position(other.get("pos")) is None:
                continue
            if self.mode == "team" and my_team and other.get("team") == my_team:
                continue
            enemies.append(other)
        return enemies

    @staticmethod
    def _enemy_cells(enemy):
        pos = position(enemy.get("pos"))
        if pos is None:
            return set()
        return {(pos[0] + dx, pos[1] + dy) for dx, dy in DIRS.values()}

    def _move_toward(self, snapshot, me, goals, allowed):
        if not goals:
            return None
        width, height, walls = self._geometry()
        occupied = {
            position(other.get("pos"))
            for other in snapshot.get("players", [])
            if isinstance(other, dict) and other.get("id") != me.get("id")
            and other.get("alive", False) and position(other.get("pos")) is not None
        }
        direction = bfs_next_step_to_any(
            position(me.get("pos")), goals, walls, occupied, width, height,
        )
        action = {"type": "move", "dir": direction} if direction else None
        if action and (action["type"], action["dir"]) in allowed:
            return action
        return None

    def _random_move(self, allowed):
        moves = [
            {"type": action_type, "dir": direction}
            for action_type in ("move", "dash")
            for direction in DIRS
            if (action_type, direction) in allowed
        ]
        return self.rng.choice(moves) if moves else {"type": "wait"}

    def decide(self, state):
        player_id = state.get("you", self.player_id)
        me = find_player(state, player_id)
        if me is None or not me.get("alive", False) or position(me.get("pos")) is None:
            return {"type": "wait"}
        legal = legal_actions(self.start_payload, state, player_id)
        allowed = {(action["type"], action.get("dir")) for action in legal}
        width, height, _ = self._geometry()
        mode_state = state.get("mode_state")
        if not isinstance(mode_state, dict):
            mode_state = self.mode_state

        def take(action):
            if action and (action["type"], action.get("dir")) in allowed:
                return action
            return None

        # Escaping active storm damage takes precedence over all other goals.
        if self.mode == "survival" and me.get("in_storm", False):
            zone = self._zone_bounds(mode_state, ([1, 1], [13, 13]))
            if not self._inside(position(me.get("pos")), zone):
                action = take(self._move_toward(
                    state, me, self._zone_cells(zone, width, height), allowed,
                ))
                return action or self._random_move(allowed)

        hp = me.get("hp", 0)
        energy = me.get("energy", 0)
        heal_threshold = self.HEAL_THRESHOLDS[self.strategy]
        if hp <= heal_threshold:
            action = take({"type": "heal"})
            if action:
                return action

        enemies = self._enemies(me, state)

        # The assigned bounty target takes priority over every generic enemy
        # attack or movement choice, including adjacent non-target enemies.
        if self.mode == "bounty":
            target_id = me.get("bounty_target")
            if not target_id:
                target_id = (mode_state.get("targets") or {}).get(me.get("id"))
            assigned = next((enemy for enemy in enemies
                             if enemy.get("id") == target_id), None)
            if assigned is not None:
                direction = adjacent_dir(me.get("pos"), assigned.get("pos"))
                if direction:
                    action = take({"type": "attack", "dir": direction})
                else:
                    action = take(self._move_toward(
                        state, me, self._enemy_cells(assigned), allowed,
                    ))
                if action:
                    return action

        adjacent = []
        for enemy in enemies:
            direction = adjacent_dir(me.get("pos"), enemy.get("pos"))
            if direction:
                adjacent.append((enemy, direction))
        if adjacent and (self.strategy != "collector" or hp < 50
                         or self.strategy == "aggressive"):
            enemy, direction = sorted(adjacent, key=lambda row: row[0]["id"])[0]
            action = take({"type": "attack", "dir": direction})
            if action:
                return action

        node = node_at(state, position(me.get("pos")))
        attack_cost = action_cost(self.rules, "attack", 8)
        if (node_is_active(node)
                and (self.strategy == "collector" or energy < attack_cost)):
            action = take({"type": "gather"})
            if action:
                return action

        # King of the Hill has an explicit movement objective.
        if self.mode == "king":
            zone = self._zone_bounds(mode_state, ([6, 6], [8, 8]))
            if not self._inside(position(me.get("pos")), zone):
                action = take(self._move_toward(
                    state, me, self._zone_cells(zone, width, height), allowed,
                ))
                if action:
                    return action

        active_nodes = {
            position(node.get("pos"))
            for node in state.get("nodes", [])
            if isinstance(node, dict) and node_is_active(node)
            and position(node.get("pos")) is not None
        }

        enemy_goals = set()
        for enemy in enemies:
            enemy_goals.update(self._enemy_cells(enemy))

        if self.strategy == "collector":
            goal_groups = (active_nodes, enemy_goals)
        elif self.strategy == "aggressive":
            goal_groups = (enemy_goals, active_nodes)
        else:
            goal_groups = (active_nodes | enemy_goals,)
        for goals in goal_groups:
            action = take(self._move_toward(state, me, goals, allowed))
            if action:
                return action
        return self._random_move(allowed)


def build_parser():
    parser = argparse.ArgumentParser(description="Run a NEON ARENA heuristic bot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--name", default="Heuristic")
    parser.add_argument("--strategy", choices=HeuristicPolicy.STRATEGIES,
                        default="balanced")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logger = (lambda *_: None) if args.quiet else print
    policy = HeuristicPolicy(args.strategy, seed=args.seed)
    run_agent(args.host, args.port, args.name, policy, logger=logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
