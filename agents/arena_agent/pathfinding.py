"""Small deterministic BFS helpers for the four-neighbor arena grid."""

from __future__ import annotations

from collections import deque

from .protocol import DIRS


def _coord(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x, y = value
    if (not isinstance(x, int) or isinstance(x, bool)
            or not isinstance(y, int) or isinstance(y, bool)):
        return None
    return x, y


def _points(values):
    result = set()
    for value in values or ():
        point = _coord(value)
        if point is not None:
            result.add(point)
    return result


def _search(start, goals, walls, occupied, width, height):
    origin = _coord(start)
    if origin is None:
        return None
    targets = _points(goals)
    if origin in targets:
        return None
    blocked = _points(walls) | _points(occupied)
    seen = {origin}
    queue = deque([(origin, None)])
    while queue:
        (x, y), first = queue.popleft()
        for direction, (dx, dy) in DIRS.items():
            nxt = (x + dx, y + dy)
            if not (0 <= nxt[0] < width and 0 <= nxt[1] < height):
                continue
            if nxt in blocked or nxt in seen:
                continue
            next_first = first or direction
            if nxt in targets:
                return next_first
            seen.add(nxt)
            queue.append((nxt, next_first))
    return None


def bfs_next_step(start, goal, walls, occupied,
                  width: int = 15, height: int = 15) -> str | None:
    """Return the first step on a shortest path, or None if unreachable."""
    return _search(start, (goal,), walls, occupied, width, height)


def bfs_next_step_to_any(start, goals, walls, occupied,
                         width: int = 15, height: int = 15) -> str | None:
    """Return the first step toward the nearest reachable goal."""
    return _search(start, goals, walls, occupied, width, height)


def adjacent_dir(a, b) -> str | None:
    """Return the cardinal direction from a to adjacent b."""
    first, second = _coord(a), _coord(b)
    if first is None or second is None:
        return None
    for direction, (dx, dy) in DIRS.items():
        if (first[0] + dx, first[1] + dy) == second:
            return direction
    return None


__all__ = ["bfs_next_step", "bfs_next_step_to_any", "adjacent_dir"]
