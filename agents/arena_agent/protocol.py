"""NEON ARENA protocol version, directions, and NDJSON codec."""

from __future__ import annotations

import json

PROTOCOL = 1
DIRS = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}


def encode(msg: dict) -> bytes:
    """Encode one protocol object as a UTF-8 NDJSON line."""
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
            + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict:
    """Decode and validate one protocol object."""
    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("line is not valid UTF-8") from exc
    elif isinstance(line, str):
        text = line
    else:
        raise ValueError("line must be bytes or text")
    try:
        message = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("line is not valid JSON") from exc
    if not isinstance(message, dict):
        raise ValueError("message must be a JSON object")
    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ValueError("message must have a non-empty string type")
    return message


__all__ = ["PROTOCOL", "DIRS", "encode", "decode"]
