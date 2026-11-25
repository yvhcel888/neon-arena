"""Command-line entry point for the NEON ARENA server."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from arena_server import __version__
from arena_server.config import ServerConfig
from arena_server.modes import MODE_ORDER
from arena_server.server import GameServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena_server",
        description="NEON ARENA authoritative game server",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--tcp-port", type=int, default=7777)
    parser.add_argument("--api-port", type=int, default=8080,
                        help="start the HTTP API on this port")
    parser.add_argument("--tick-ms", type=int, default=15000)
    parser.add_argument("--min-turn-ms", type=int, default=250)
    parser.add_argument("--turn-limit", type=int, default=80)
    parser.add_argument("--min-players", type=int, default=2)
    parser.add_argument("--max-players", type=int, default=4)
    parser.add_argument("--lobby-wait-ms", type=int, default=5000)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--no-logs", action="store_true")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--max-missed-turns", type=int, default=4)
    parser.add_argument("--max-clients", type=int, default=32)
    parser.add_argument("--cors-origin", default="*")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--mode", choices=("rotation", *MODE_ORDER),
                        default="rotation")
    parser.add_argument("--version", action="version",
                        version=f"Neon Arena {__version__}")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = ServerConfig(
        host=args.host,
        tcp_port=args.tcp_port,
        api_port=args.api_port,
        tick_ms=args.tick_ms,
        min_turn_ms=args.min_turn_ms,
        turn_limit=args.turn_limit,
        min_players=args.min_players,
        max_players=args.max_players,
        lobby_wait_ms=args.lobby_wait_ms,
        max_missed_turns=args.max_missed_turns,
        seed=args.seed,
        log_dir=args.log_dir,
        no_logs=args.no_logs,
        cors_origin=args.cors_origin,
        max_clients=args.max_clients,
        verbose=args.verbose,
        mode=args.mode,
    )
    try:
        server = GameServer(config)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        asyncio.run(server.run_forever())
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
