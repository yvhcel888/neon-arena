"""Live terminal spectator and JSONL replay viewer."""

from __future__ import annotations

import argparse
import os
import socket
import time

from arena_agent.protocol import PROTOCOL, decode, encode
from arena_agent.render import MODE_LABELS, render_board


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def _title(start):
    mode = str(start.get("mode") or "classic")
    return f"NEON ARENA | {MODE_LABELS.get(mode, mode)} [{mode}]"


def _end_text(end):
    lines = [f"Match ended: {end.get('reason', 'unknown')} "
             f"after {end.get('turns', '?')} turns"]
    winner = end.get("winner")
    if isinstance(winner, dict):
        lines.append(f"Winner: {winner.get('name', winner.get('id', '?'))}")
    standings = end.get("standings", [])
    if isinstance(standings, list):
        lines.append("Rankings:")
        for index, row in enumerate(standings, 1):
            if not isinstance(row, dict):
                continue
            lines.append(
                f"  {index}. {row.get('name', row.get('id', '?'))} "
                f"score={row.get('score', 0)} hp={row.get('hp', 0)} "
                f"alive={row.get('alive', False)}",
            )
    return "\n".join(lines)


def _lobby_text(lobby):
    players = lobby.get("players", [])
    names = ", ".join(str(row.get("name", "?")) for row in players
                      if isinstance(row, dict))
    return (f"Lobby: {len(players)}/{lobby.get('max_players', '?')} players"
            f" | mode={lobby.get('mode_label', lobby.get('mode', '?'))}"
            f" | starts_in_ms={lobby.get('starts_in_ms')} | {names}")


def run_replay(path, delay=0.0, color=True, plain=False, output=print):
    """Render start/state/end JSONL records without opening a socket."""
    start = {}
    with open(path, "r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                message = decode(line)
            except ValueError as exc:
                output(f"Skipping replay line {line_number}: {exc}")
                continue
            kind = message.get("type")
            rendered = None
            if kind == "start":
                start = message
                rendered = _title(start)
            elif kind == "state":
                rendered = render_board(start, message, color=color and not plain)
            elif kind == "end":
                rendered = _end_text(message)
            if rendered is not None:
                output(rendered)
                if delay > 0:
                    time.sleep(delay)
    return 0


def run_spectator(host="127.0.0.1", port=7777, once=False,
                  color=True, plain=False, output=print):
    """Follow live matches until EOF or until --once sees the first end."""
    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(None)
    stream = sock.makefile("rwb")
    try:
        line = stream.readline()
        if not line:
            raise ConnectionError("connection closed before welcome")
        welcome = decode(line)
        if welcome.get("type") != "welcome" or welcome.get("protocol") != PROTOCOL:
            raise ConnectionError("unsupported server protocol")
        stream.write(encode({"type": "spectate"}))
        stream.flush()
        start = {}
        while True:
            line = stream.readline()
            if not line:
                return 0
            message = decode(line)
            kind = message.get("type")
            rendered = None
            if kind == "lobby":
                rendered = _lobby_text(message)
            elif kind == "start":
                start = message
                rendered = _title(start)
            elif kind == "state":
                rendered = render_board(start, message, color=color and not plain)
            elif kind == "end":
                rendered = _end_text(message)
                start = {}
            if rendered is not None:
                if not plain:
                    clear_screen()
                output(rendered)
            if kind == "end" and once:
                return 0
    finally:
        try:
            stream.close()
        finally:
            sock.close()


def build_parser():
    parser = argparse.ArgumentParser(description="Watch NEON ARENA in a terminal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--replay", metavar="JSONL")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    color = not args.no_color and not args.plain
    if args.replay:
        return run_replay(args.replay, delay=args.delay, color=color,
                          plain=args.plain)
    return run_spectator(args.host, args.port, once=args.once,
                         color=color, plain=args.plain)


if __name__ == "__main__":
    raise SystemExit(main())
