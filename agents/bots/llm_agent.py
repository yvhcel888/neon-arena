"""Optional LLM-backed policy using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.request

from arena_agent.client import run_agent
from arena_agent.policy import (
    Policy, arena_geometry, find_player, legal_actions,
)
from arena_agent.protocol import DIRS
from .heuristic import HeuristicPolicy

ACTION_TYPES = {"move", "dash", "attack", "gather", "shield", "heal", "wait"}
DIRECTIONAL = {"move", "dash", "attack"}
MODE_DESCRIPTIONS = {
    "classic": "Last player standing or highest score.",
    "king": "Hold the center zone to build score.",
    "team": "Two teams of two; friendly fire is disabled.",
    "survival": "Stay inside the shrinking safe zone.",
    "bounty": "Hunt your assigned target for bonus score.",
}
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_TIMEOUT_MS = 20000


def parse_action(text):
    """Extract the first JSON object and return a canonical legal action."""
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, index)
        except (json.JSONDecodeError, RecursionError):
            continue
        if not isinstance(value, dict):
            continue
        action_type = value.get("type")
        if action_type not in ACTION_TYPES:
            return None
        if action_type in DIRECTIONAL:
            direction = value.get("dir")
            if not isinstance(direction, str) or direction not in DIRS:
                return None
            return {"type": action_type, "dir": direction}
        return {"type": action_type}
    return None


def _env_timeout():
    raw = os.environ.get("NEON_ARENA_LLM_TIMEOUT_MS")
    if raw is None:
        return DEFAULT_TIMEOUT_MS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_MS
    return value if value > 0 else DEFAULT_TIMEOUT_MS


class LlmPolicy(Policy):
    """Ask an OpenAI-compatible endpoint once per shared decision window."""

    def __init__(self, fallback=True, logger=print, opener=None, clock=None,
                 fallback_policy=None):
        self.logger = logger
        self.opener = opener or urllib.request.urlopen
        self.clock = clock or time.time
        if fallback_policy is not None:
            self.fallback = fallback_policy
        else:
            self.fallback = HeuristicPolicy() if fallback else None
        self.start_payload = {}
        self.mode = "classic"
        self.mode_state = {}
        self.tick_ms = 0
        self.timeout_ms = 0.0
        self.expired_actions = []
        self._request_lock = threading.Lock()
        self._request_thread = None

    def on_start(self, start):
        self.start_payload = start
        self.mode = start.get("mode", "classic")
        self.mode_state = start.get("mode_state") or {}
        tick = start.get("tick_ms", 0)
        self.tick_ms = tick if isinstance(tick, (int, float)) and tick >= 0 else 0
        # Reserve at least 20% of the server window for parsing, fallback,
        # client-side deadline checks, and socket submission.
        self.timeout_ms = min(_env_timeout(), self.tick_ms * 0.8)
        self.expired_actions = []
        if self.fallback is not None:
            self.fallback.on_start(start)

    def build_prompt(self, state):
        you = state.get("you", self.start_payload.get("you"))
        me = find_player(state, you)
        enemies = [row for row in state.get("players", [])
                   if isinstance(row, dict) and row.get("id") != you
                   and row.get("alive", False)]
        width, height, walls = arena_geometry(self.start_payload)
        payload = {
            "arena": {
                "width": width, "height": height,
                "walls": [list(wall) for wall in sorted(walls)],
            },
            "legal_actions": legal_actions(self.start_payload, state, you),
            "rules": self.start_payload.get("rules", {}),
            "mode": state.get("mode", self.mode),
            "mode_description": MODE_DESCRIPTIONS.get(
                state.get("mode", self.mode), "Unknown mode.",
            ),
            "mode_state": state.get("mode_state", self.mode_state),
            "you": me,
            "enemies": enemies,
            "nodes": state.get("nodes", []),
            "recent_events": state.get("events", [])[-12:],
        }
        return (
            "You are a NEON ARENA agent. All players use the same shared decision "
            "window; there is no real-time control. Choose exactly one action from "
            "legal_actions for the current turn. Use move/dash/attack with dir n/e/s/w, or "
            "gather/shield/heal/wait. Respect walls, occupants, energy, friendly "
            "players, and the mode objective. Return only the action object.\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                         default=str)
        )

    def _complete(self, prompt, timeout_seconds):
        base_url = os.environ.get("NEON_ARENA_LLM_BASE_URL", DEFAULT_BASE_URL)
        model = os.environ.get("NEON_ARENA_LLM_MODEL", "neon-arena")
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "You output one NEON ARENA action JSON object and no prose."
                )},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("NEON_ARENA_LLM_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=body, headers=headers, method="POST",
        )
        with self.opener(request, timeout=timeout_seconds) as response:
            raw = response.read()
        result = json.loads(raw.decode("utf-8"))
        return result["choices"][0]["message"]["content"]

    def _fallback_action(self, state):
        if self.fallback is None:
            return {"type": "wait"}
        return self.fallback.decide(state) or {"type": "wait"}

    def _deadline(self, state):
        value = state.get("reply_by_ms")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return self.clock() * 1000 + self.tick_ms

    def _expire(self, state, action):
        self.expired_actions.append({
            "turn": state.get("turn"), "action": dict(action),
            "reason": "turn_deadline_passed",
        })
        self.logger(f"turn {state.get('turn')} action expired locally")
        return None

    def _request_in_flight(self):
        with self._request_lock:
            return (self._request_thread is not None
                    and self._request_thread.is_alive())

    def _finish(self, state, deadline, action):
        if self.clock() * 1000 >= deadline:
            return self._expire(state, action)
        return action

    def decide(self, state):
        deadline = self._deadline(state)
        if self.clock() * 1000 >= deadline:
            return self._expire(state, self._fallback_action(state))
        if self._request_in_flight():
            return self._finish(state, deadline, self._fallback_action(state))

        try:
            prompt = self.build_prompt(state)
        except Exception as exc:
            self.logger(f"LLM error: {type(exc).__name__}")
            return self._finish(state, deadline, self._fallback_action(state))

        remaining_ms = deadline - self.clock() * 1000
        if remaining_ms <= 0:
            return self._expire(state, self._fallback_action(state))
        wait_seconds = min(self.timeout_ms, remaining_ms * 0.9) / 1000
        if wait_seconds <= 0:
            return self._finish(state, deadline, self._fallback_action(state))

        finished = threading.Event()
        result = {}

        def request():
            try:
                result["text"] = self._complete(
                    prompt, max(0.001, wait_seconds),
                )
            except BaseException as exc:
                # Store only the type: HTTP errors can echo credentials.
                result["error"] = type(exc).__name__
            finally:
                with self._request_lock:
                    if self._request_thread is threading.current_thread():
                        self._request_thread = None
                finished.set()

        worker = threading.Thread(target=request, name="neon-arena-llm",
                                  daemon=True)
        start_error = None
        with self._request_lock:
            busy = (self._request_thread is not None
                    and self._request_thread.is_alive())
            if not busy:
                self._request_thread = worker
                try:
                    worker.start()
                except BaseException as exc:
                    self._request_thread = None
                    start_error = type(exc).__name__
        if busy:
            return self._finish(state, deadline, self._fallback_action(state))
        if start_error is not None:
            self.logger(f"LLM error: {start_error}")
            return self._finish(state, deadline, self._fallback_action(state))

        if not finished.wait(wait_seconds):
            # Socket timeouts do not bound a trickling response. The worker is
            # daemonized and remains tracked so later turns cannot overlap it.
            self.logger("LLM request exceeded turn budget")
            action = self._fallback_action(state)
        elif "error" in result:
            self.logger(f"LLM error: {result['error']}")
            action = self._fallback_action(state)
        else:
            try:
                action = parse_action(result.get("text"))
                you = state.get("you", self.start_payload.get("you"))
                if action not in legal_actions(self.start_payload, state, you):
                    action = self._fallback_action(state)
            except Exception as exc:
                self.logger(f"LLM error: {type(exc).__name__}")
                action = self._fallback_action(state)
        return self._finish(state, deadline, action)


def build_parser():
    parser = argparse.ArgumentParser(description="Run a NEON ARENA LLM bot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--name", default="LLM")
    parser.add_argument("--no-fallback", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logger = (lambda *_: None) if args.quiet else print
    policy = LlmPolicy(fallback=not args.no_fallback, logger=logger)
    run_agent(args.host, args.port, args.name, policy, logger=logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
