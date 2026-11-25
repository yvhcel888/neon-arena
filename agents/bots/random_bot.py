"""Deterministic random bot and command-line entry point."""

from __future__ import annotations

import argparse
import random
import zlib

from arena_agent.client import run_agent
from arena_agent.policy import Policy, find_player, legal_actions


class RandomPolicy(Policy):
    """Choose uniformly from actions that are legal in the local snapshot."""

    def __init__(self, name="Random"):
        self.name = name
        self.rng = random.Random(zlib.crc32(name.encode("utf-8")))
        self.start_payload = None
        self.player_id = None

    def on_start(self, start):
        self.start_payload = start
        self.player_id = start.get("you")
        me = find_player(start, self.player_id)
        if me and me.get("name"):
            self.name = me["name"]
            self.rng = random.Random(zlib.crc32(self.name.encode("utf-8")))

    def decide(self, state):
        player_id = state.get("you", self.player_id)
        actions = legal_actions(self.start_payload or {}, state, player_id)
        if not actions:
            return {"type": "wait"}
        return self.rng.choice(actions)


def build_parser():
    parser = argparse.ArgumentParser(description="Run a NEON ARENA random bot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--name", default="Random")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logger = (lambda *_: None) if args.quiet else print
    run_agent(args.host, args.port, args.name, RandomPolicy(args.name),
              logger=logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
