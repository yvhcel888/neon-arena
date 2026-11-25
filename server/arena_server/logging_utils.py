"""Per-match JSONL logging."""

from __future__ import annotations

import json
from pathlib import Path


class MatchLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", buffering=1)
        self._closed = False

    def write(self, message: dict) -> None:
        if self._closed:
            return
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._file.close()


class NullLog:
    def write(self, message: dict) -> None:
        pass

    def close(self) -> None:
        pass
