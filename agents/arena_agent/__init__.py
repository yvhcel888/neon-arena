"""Standard-library client SDK for the NEON ARENA TCP protocol."""

from .client import ArenaClient, run_agent
from .pathfinding import adjacent_dir, bfs_next_step
from .policy import Policy, safe_decide
from .protocol import DIRS, PROTOCOL, decode, encode
from .render import render_board

__all__ = [
    "ArenaClient", "DIRS", "PROTOCOL", "Policy", "adjacent_dir",
    "bfs_next_step", "decode", "encode", "render_board", "run_agent",
    "safe_decide",
]
