"""Transport-neutral participant records."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


@dataclass(eq=False)
class Participant:
    name: str
    kind: str
    transport: str
    player_id: str | None = None
    state: str = "lobby"
    missed_turns: int = 0
    tcp: Any = None
    session: Any = None
    match: Any = None
    joined_at: float = field(default_factory=time.monotonic)
