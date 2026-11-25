"""FIFO lobby queue and countdown snapshots."""

from __future__ import annotations

import time


class Lobby:
    def __init__(self, min_players: int = 2, max_players: int = 4):
        self.min_players = min_players
        self.max_players = max_players
        self.waiting: list = []
        self.deadline: float | None = None

    def add(self, participant) -> bool:
        if participant in self.waiting:
            return False
        self.waiting.append(participant)
        return True

    def remove(self, participant) -> bool:
        try:
            self.waiting.remove(participant)
        except ValueError:
            return False
        return True

    def take(self, count: int) -> list:
        count = max(0, min(int(count), len(self.waiting)))
        taken = self.waiting[:count]
        del self.waiting[:count]
        return taken

    def snapshot(self, mode: str | None = None,
                 mode_label: str | None = None,
                 mode_description: str | None = None,
                 min_players: int | None = None,
                 now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        minimum = self.min_players if min_players is None else min_players
        starts_in_ms = None
        if len(self.waiting) >= minimum and self.deadline is not None:
            starts_in_ms = max(0, int((self.deadline - now) * 1000))
        payload = {
            "players": [
                {"name": participant.name, "kind": participant.kind}
                for participant in self.waiting
            ],
            "min_players": minimum,
            "max_players": self.max_players,
            "starts_in_ms": starts_in_ms,
        }
        if mode is not None:
            payload["mode"] = mode
        if mode_label is not None:
            payload["mode_label"] = mode_label
        if mode_description is not None:
            payload["mode_description"] = mode_description
        return payload
