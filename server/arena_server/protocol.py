"""Shared TCP protocol constants, validation, and errors."""

from __future__ import annotations

import unicodedata

from arena_server.engine import ActionError

PROTOCOL = 1
MAX_LINE_BYTES = 65536


class ServerFull(Exception):
    """Raised when a connection or lobby cannot accept another client."""


def make_error(code: str, message: str, turn: int | None = None) -> dict:
    payload = {"type": "error", "code": code, "message": message}
    if turn is not None:
        payload["turn"] = turn
    return payload


def validate_name(raw) -> str:
    if not isinstance(raw, str):
        raise ValueError("name must be a string")
    name = raw.strip()
    if not name:
        raise ValueError("name must not be empty")
    if len(name) > 20:
        raise ValueError("name must be at most 20 characters")
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise ValueError("name must not contain control characters")
    return name


__all__ = [
    "PROTOCOL", "MAX_LINE_BYTES", "ActionError", "ServerFull",
    "make_error", "validate_name",
]
