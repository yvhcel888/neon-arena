from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import random

from arena_server.modes import create_game_mode

WIDTH, HEIGHT = 15, 15
SPAWN_POINTS = ((1, 1), (13, 13), (13, 1), (1, 13))
NODE_POINTS = ((7, 7), (7, 3), (3, 7), (11, 7), (7, 11))


@dataclass(frozen=True)
class MapData:
    width: int
    height: int
    walls: frozenset[tuple[int, int]]
    nodes: tuple[tuple[int, int], ...]


def _reserved() -> set[tuple[int, int]]:
    reserved = set()
    for x, y in (*SPAWN_POINTS, *NODE_POINTS):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                reserved.add((x + dx, y + dy))
    return reserved


def _connected(walls, points) -> bool:
    points = set(points)
    start = next(iter(points))
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if not (0 <= nxt[0] < WIDTH and 0 <= nxt[1] < HEIGHT):
                continue
            if nxt in walls or nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return points <= seen


def arena_connected(map_data: MapData) -> bool:
    return _connected(map_data.walls, (*SPAWN_POINTS, *NODE_POINTS))


def generate_map(seed: int) -> MapData:
    reserved = _reserved()
    candidates = []
    for x in range(1, WIDTH - 1):
        for y in range(1, HEIGHT - 1):
            pos = (x, y)
            rot = (WIDTH - 1 - x, HEIGHT - 1 - y)
            if pos >= rot or pos in reserved or rot in reserved:
                continue
            if pos == rot:
                continue
            candidates.append((pos, rot))
    for attempt in range(100):
        rng = random.Random(seed * 1009 + attempt)
        rng.shuffle(candidates)
        walls = set()
        for a, b in candidates:
            if len(walls) >= 20:
                break
            if a not in walls and b not in walls:
                walls.add(a)
                walls.add(b)
        m = MapData(WIDTH, HEIGHT, frozenset(walls), NODE_POINTS)
        if arena_connected(m):
            return m
    return MapData(WIDTH, HEIGHT, frozenset(), NODE_POINTS)


DIRS = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}

MOVE_TYPES = ("move", "dash")
COST_ACTIONS = ("dash", "attack", "heal", "shield")


class ActionError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass
class Player:
    id: str
    name: str
    kind: str
    pos: tuple[int, int]
    hp: int
    shield: int
    energy: int
    score: int
    alive: bool
    damage_dealt: int
    kills: int
    gathered: int
    forfeited: bool
    missed_turns: int


@dataclass
class Node:
    pos: tuple[int, int]
    cooldown: int = 0

    @property
    def active(self) -> bool:
        return self.cooldown == 0


def _as_coord(pos: tuple[int, int]) -> list[int]:
    return [pos[0], pos[1]]


class Engine:
    def __init__(self, rules, players: list[tuple[str, str]], seed: int,
                 match_id: str = "local", map_data: MapData | None = None,
                 max_missed_turns: int = 4, mode: str = "classic"):
        self.rules = rules
        self._action_costs = {
            "dash": rules.dash_cost,
            "attack": rules.attack_cost,
            "heal": rules.heal_cost,
            "shield": rules.shield_cost,
        }
        self.seed = seed
        self.match_id = match_id
        self.max_missed_turns = max_missed_turns
        self.turn_limit = rules.turn_limit
        self.map = map_data if map_data is not None else generate_map(seed)
        self.nodes = [Node(pos, 0) for pos in self.map.nodes]

        spawns = self._spawn_points(len(players))
        self.players: dict[str, Player] = {}
        for index, (name, kind) in enumerate(players, start=1):
            player_id = f"P{index}"
            self.players[player_id] = Player(
                id=player_id,
                name=name,
                kind=kind,
                pos=spawns[index - 1],
                hp=rules.max_hp,
                shield=0,
                energy=rules.start_energy,
                score=0,
                alive=True,
                damage_dealt=0,
                kills=0,
                gathered=0,
                forfeited=False,
                missed_turns=0,
            )

        self.mode_name = mode
        self.mode = create_game_mode(self, mode)

        self.turn = 1
        self.finished = False
        self.end_reason: str | None = None
        self.completed_turns = 0
        self.last_events: list[dict] = []
        self.events_turn = 0

    @property
    def mode_state(self) -> dict:
        return self.mode.state

    def _spawn_points(self, count: int) -> list[tuple[int, int]]:
        rng = random.Random(self.seed)
        if count == 1:
            return [rng.choice(SPAWN_POINTS)]
        if count == 2:
            pairs = (
                (SPAWN_POINTS[0], SPAWN_POINTS[1]),
                (SPAWN_POINTS[2], SPAWN_POINTS[3]),
            )
            return list(rng.choice(pairs))
        if count == 3:
            return rng.sample(SPAWN_POINTS, 3)
        if count == 4:
            spawns = list(SPAWN_POINTS)
            rng.shuffle(spawns)
            return spawns
        raise ValueError("players must be between 1 and 4")

    def _walkable(self, pos: tuple[int, int]) -> bool:
        x, y = pos
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            return False
        if x == 0 or y == 0 or x == self.map.width - 1 or y == self.map.height - 1:
            return False
        return pos not in self.map.walls

    def _node_at(self, pos: tuple[int, int]) -> Node | None:
        for node in self.nodes:
            if node.pos == pos:
                return node
        return None

    @staticmethod
    def _canonical_action(action) -> dict | None:
        if not isinstance(action, dict):
            return None
        action_type = action.get("type")
        if action_type in MOVE_TYPES or action_type == "attack":
            direction = action.get("dir")
            if not isinstance(direction, str) or direction not in DIRS:
                return None
            return {"type": action_type, "dir": direction}
        if action_type in ("gather", "shield", "heal", "wait"):
            return {"type": action_type}
        return None

    def validate_action(self, player_id: str, action, turn: int) -> dict:
        if turn != self.turn:
            raise ActionError(
                "stale_turn",
                f"turn {turn} is stale; current turn is {self.turn}",
            )
        player = self.players.get(player_id)
        if player is None:
            raise ActionError("not_in_match", f"{player_id} is not in this match")
        if not player.alive:
            raise ActionError("not_alive", f"{player_id} is not alive")
        if not isinstance(action, dict):
            raise ActionError("invalid_action", "action must be an object")

        action_type = action.get("type")
        if action_type == "move":
            direction = action.get("dir")
            if not isinstance(direction, str) or direction not in DIRS:
                raise ActionError("invalid_action", f"invalid direction {direction!r}")
            dx, dy = DIRS[direction]
            target = (player.pos[0] + dx, player.pos[1] + dy)
            if not self._walkable(target):
                raise ActionError("wall", f"cannot move into {_as_coord(target)}")
            return {"type": "move", "dir": direction}

        if action_type == "dash":
            direction = action.get("dir")
            if not isinstance(direction, str) or direction not in DIRS:
                raise ActionError("invalid_action", f"invalid direction {direction!r}")
            dx, dy = DIRS[direction]
            middle = (player.pos[0] + dx, player.pos[1] + dy)
            distance = self.rules.dash_distance
            target = (player.pos[0] + dx * distance, player.pos[1] + dy * distance)
            if not self._walkable(middle) or not self._walkable(target):
                raise ActionError("wall", f"cannot dash into {_as_coord(target)}")
            if player.energy < self._action_costs["dash"]:
                raise ActionError(
                    "insufficient_energy",
                    f"dash needs {self._action_costs['dash']} energy",
                )
            return {"type": "dash", "dir": direction}

        if action_type == "attack":
            direction = action.get("dir")
            if not isinstance(direction, str) or direction not in DIRS:
                raise ActionError("invalid_action", f"invalid direction {direction!r}")
            if player.energy < self._action_costs["attack"]:
                raise ActionError(
                    "insufficient_energy",
                    f"attack needs {self._action_costs['attack']} energy",
                )
            return {"type": "attack", "dir": direction}

        if action_type == "gather":
            node = self._node_at(player.pos)
            if node is None or not node.active:
                raise ActionError("no_active_node", "no active node here")
            return {"type": "gather"}

        if action_type == "shield":
            if player.energy < self._action_costs["shield"]:
                raise ActionError(
                    "insufficient_energy",
                    f"shield needs {self._action_costs['shield']} energy",
                )
            if player.shield >= self.rules.max_shield:
                raise ActionError("shield_full", "shield is already full")
            return {"type": "shield"}

        if action_type == "heal":
            if player.energy < self._action_costs["heal"]:
                raise ActionError(
                    "insufficient_energy",
                    f"heal needs {self._action_costs['heal']} energy",
                )
            if player.hp >= self.rules.max_hp:
                raise ActionError("full_hp", "hp is already full")
            return {"type": "heal"}

        if action_type == "wait":
            return {"type": "wait"}

        raise ActionError("invalid_action", f"unknown action type {action_type!r}")

    def resolve(self, actions: dict[str, dict]) -> list[dict]:
        if self.finished:
            return []
        actions = actions or {}
        current_turn = self.turn
        alive = [p for p in self.players.values() if p.alive]
        events: list[dict] = []

        chosen: dict[str, dict] = {}
        for player in alive:
            canonical = self._canonical_action(actions.get(player.id))
            valid = canonical is not None
            if valid and canonical["type"] in COST_ACTIONS:
                cost = self._action_costs[canonical["type"]]
                valid = player.energy >= cost
            if valid:
                player.missed_turns = 0
                chosen[player.id] = canonical
            else:
                player.missed_turns += 1
                chosen[player.id] = {"type": "wait"}

        for player in alive:
            action = chosen[player.id]
            if action["type"] not in COST_ACTIONS:
                continue
            cost = self._action_costs[action["type"]]
            if player.energy < cost:
                chosen[player.id] = {"type": "wait"}
                continue
            player.energy -= cost

        start_positions = {player.pos for player in alive}
        movers: list[tuple[Player, dict]] = []
        targets: dict[str, tuple[int, int]] = {}
        for player in alive:
            action = chosen[player.id]
            if action["type"] not in MOVE_TYPES:
                continue
            dx, dy = DIRS[action["dir"]]
            distance = self.rules.dash_distance if action["type"] == "dash" else 1
            target = (player.pos[0] + dx * distance, player.pos[1] + dy * distance)
            movers.append((player, action))
            targets[player.id] = target

        target_counts: dict[tuple[int, int], int] = {}
        for target in targets.values():
            target_counts[target] = target_counts.get(target, 0) + 1
        target_set = set(targets.values())

        reasons: dict[str, str] = {}
        for player, action in movers:
            target = targets[player.id]
            if not self._walkable(target):
                reasons[player.id] = "occupied"
                continue
            if target in start_positions:
                reasons[player.id] = "occupied"
                continue
            if target_counts[target] > 1:
                reasons[player.id] = "collision"
                continue
            if action["type"] == "dash":
                dx, dy = DIRS[action["dir"]]
                middle = (player.pos[0] + dx, player.pos[1] + dy)
                if not self._walkable(middle):
                    reasons[player.id] = "occupied"
                    continue
                if middle in start_positions:
                    reasons[player.id] = "occupied"
                    continue
                if middle in target_set:
                    reasons[player.id] = "collision"
                    continue

        for player, action in movers:
            if player.id in reasons:
                events.append({
                    "type": "blocked",
                    "player": player.id,
                    "action": action["type"],
                    "dir": action["dir"],
                    "reason": reasons[player.id],
                })
                continue
            old_pos = player.pos
            player.pos = targets[player.id]
            events.append({
                "type": action["type"],
                "player": player.id,
                "from": _as_coord(old_pos),
                "to": _as_coord(player.pos),
            })

        for player in alive:
            action = chosen[player.id]
            action_type = action["type"]
            if action_type == "shield":
                amount = min(self.rules.shield_amount,
                             self.rules.max_shield - player.shield)
                if amount > 0:
                    player.shield += amount
                    events.append({
                        "type": "shield", "player": player.id,
                        "amount": amount, "shield": player.shield,
                    })
            elif action_type == "heal":
                amount = min(self.rules.heal_amount,
                             self.rules.max_hp - player.hp)
                if amount > 0:
                    player.hp += amount
                    events.append({
                        "type": "heal", "player": player.id,
                        "amount": amount, "hp": player.hp,
                    })
            elif action_type == "gather":
                node = self._node_at(player.pos)
                if node is not None and node.active:
                    node.cooldown = self.rules.node_cooldown
                    player.energy = min(
                        self.rules.max_energy,
                        player.energy + self.rules.gather_energy,
                    )
                    player.score += self.rules.gather_score
                    player.gathered += 1
                    events.append({
                        "type": "gather", "player": player.id,
                        "pos": _as_coord(player.pos),
                        "energy_gain": self.rules.gather_energy,
                        "score_gain": self.rules.gather_score,
                    })

        occupants = {player.pos: player for player in alive}
        damage_by_target: dict[str, dict[str, int]] = {}
        for player in alive:
            action = chosen[player.id]
            if action["type"] != "attack":
                continue
            dx, dy = DIRS[action["dir"]]
            target_pos = (player.pos[0] + dx, player.pos[1] + dy)
            target = occupants.get(target_pos)
            events.append({
                "type": "attack", "player": player.id,
                "dir": action["dir"],
                "target": _as_coord(target_pos) if target is not None else None,
            })
            if target is None:
                continue
            shield_damage = min(target.shield, self.rules.attack_damage)
            hp_damage = self.rules.attack_damage - shield_damage
            target.shield -= shield_damage
            target.hp -= hp_damage
            if hp_damage > 0:
                player.damage_dealt += hp_damage
                player.score += (hp_damage * self.rules.damage_score
                                 * self.mode.damage_multiplier(player, target))
                attackers = damage_by_target.setdefault(target.id, {})
                attackers[player.id] = attackers.get(player.id, 0) + hp_damage
            events.append({
                "type": "damage", "player": player.id, "target": target.id,
                "hp_damage": hp_damage, "shield_damage": shield_damage,
            })

        for player in alive:
            if player.hp > 0:
                continue
            player.alive = False
            attackers = damage_by_target.get(player.id, {})
            killer = None
            if attackers:
                most_damage = max(attackers.values())
                killer = min(player_id for player_id, damage in attackers.items()
                             if damage == most_damage)
                self.players[killer].kills += 1
                self.players[killer].score += self.mode.kill_reward(
                    self.players[killer], player,
                )
            events.append({"type": "death", "player": player.id, "killer": killer})

        self.mode.after_deaths(events)

        for player in alive:
            if player.alive:
                player.energy = min(
                    self.rules.max_energy,
                    player.energy + self.rules.energy_regen,
                )
        for node in self.nodes:
            if node.cooldown > 0:
                node.cooldown -= 1

        for player in alive:
            if (player.alive and not player.forfeited
                    and player.missed_turns >= self.max_missed_turns):
                player.alive = False
                player.hp = 0
                player.forfeited = True
                events.append({"type": "forfeit", "player": player.id})

        self.mode.after_missed(events)
        self.last_events = events
        self.events_turn = current_turn
        self.completed_turns = current_turn
        reason = self._end_reason()
        if reason is not None:
            self.finished = True
            self.end_reason = reason
        else:
            self.turn = current_turn + 1
        return events

    def _end_reason(self) -> str | None:
        alive_count = self.mode.alive_unit_count()
        if alive_count == 1:
            return "last_standing"
        if alive_count == 0:
            return "mutual_destruction"
        if self.mode.score_limit_reached():
            return "score_limit"
        if self.completed_turns >= self.turn_limit:
            return "turn_limit"
        return None

    def _player_payload(self, player: Player) -> dict:
        payload = {
            "id": player.id,
            "name": player.name,
            "kind": player.kind,
            "pos": _as_coord(player.pos),
            "hp": player.hp,
            "shield": player.shield,
            "energy": player.energy,
            "score": player.score,
            "alive": player.alive,
            "stats": {
                "damage_dealt": player.damage_dealt,
                "kills": player.kills,
                "gathered": player.gathered,
                "forfeited": player.forfeited,
            },
        }
        payload.update(self.mode.player_fields(player))
        return payload

    def standings(self) -> list[dict]:
        players = sorted(
            self.players.values(),
            key=lambda player: (
                not player.alive, -player.score, -player.hp,
                -player.energy, player.id,
            ),
        )
        return [self._player_payload(player) for player in players]

    def end_payload(self, reason: str | None = None) -> dict:
        reason = self.end_reason if reason is None else reason
        standings = self.standings()
        winner = None
        if reason != "aborted" and standings:
            winner = self.mode.winner(standings)
        payload = {
            "type": "end",
            "match_id": self.match_id,
            "reason": reason,
            "turns": self.completed_turns,
            "winner": winner,
            "standings": standings,
            "events_turn": self.events_turn,
            "events": [dict(event) for event in self.last_events],
        }
        payload.update(self.mode.end_extras())
        payload["mode"] = self.mode_name
        payload["mode_state"] = self.mode_state
        return payload

    def forfeit(self, player_id: str) -> bool:
        player = self.players.get(player_id)
        if self.finished or player is None or not player.alive:
            return False
        player.alive = False
        player.hp = 0
        player.forfeited = True
        self.last_events = [{"type": "forfeit", "player": player_id}]
        self.mode.on_forfeit(player_id, self.last_events)
        self.events_turn = self.turn
        reason = self._end_reason()
        if reason is not None:
            self.finished = True
            self.end_reason = reason
        return True

    def state_payload(self, for_player: str | None = None) -> dict:
        payload = {
            "turn": self.turn,
            "turn_limit": self.turn_limit,
            "players": [self._player_payload(player)
                        for player in self.players.values()],
            "nodes": [
                {
                    "pos": _as_coord(node.pos),
                    "cooldown": node.cooldown,
                    "active": node.active,
                }
                for node in self.nodes
            ],
            "events_turn": self.events_turn,
            "events": [dict(event) for event in self.last_events],
            "mode": self.mode_name,
            "mode_state": self.mode_state,
        }
        if for_player is not None:
            payload["you"] = for_player
        return payload

    def start_payload(self, for_player: str | None = None) -> dict:
        payload = {
            "match_id": self.match_id,
            "seed": self.seed,
            "turn_limit": self.turn_limit,
            "rules": self.rules.to_dict(),
            "arena": {
                "width": self.map.width,
                "height": self.map.height,
                "walls": [_as_coord(pos) for pos in sorted(self.map.walls)],
                "nodes": [_as_coord(pos) for pos in self.map.nodes],
                "spawns": [_as_coord(pos) for pos in SPAWN_POINTS],
            },
            "players": [
                {
                    "id": player.id,
                    "name": player.name,
                    "kind": player.kind,
                    "pos": _as_coord(player.pos),
                }
                for player in self.players.values()
            ],
            "mode": self.mode_name,
            "mode_state": self.mode_state,
        }
        if for_player is not None:
            payload["you"] = for_player
        return payload
