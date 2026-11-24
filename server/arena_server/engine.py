from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import random

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
