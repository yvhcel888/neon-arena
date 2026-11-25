"""Blocking NDJSON TCP client for NEON ARENA agents."""

from __future__ import annotations

from contextlib import suppress
import socket
import time

from .policy import Policy, find_player, safe_decide
from .protocol import PROTOCOL, decode, encode


class ArenaClient:
    def __init__(self, host, port, name, policy, requeue=False, logger=print):
        self.host = host
        self.port = port
        self.name = name
        self.policy = policy
        self.requeue = requeue
        self.logger = logger
        self._reset_match_state()

    def _reset_match_state(self):
        self.player_id = None
        self.start_payload = None
        self.expired_actions = []

    def run(self):
        """Connect with bounded backoff; optionally rejoin after each match."""
        delay = 1
        while True:
            try:
                self._run_once()
            except (ConnectionError, OSError, TimeoutError) as exc:
                self._reset_match_state()
                self.logger(f"connection error: {type(exc).__name__}")
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            delay = 1
            if not self.requeue:
                return
            self._reset_match_state()
            time.sleep(1)

    def _run_once(self):
        sock = socket.create_connection((self.host, self.port), timeout=10)
        # The connection timeout is for establishment only. LLM matches use
        # 30/60-second decision windows, so established reads must not time out.
        sock.settimeout(None)
        stream = None
        try:
            stream = sock.makefile("rwb")
            line = stream.readline()
            if not line:
                raise ConnectionError("connection closed before welcome")
            try:
                welcome = decode(line)
            except ValueError as exc:
                raise ConnectionError("invalid welcome message") from exc
            if welcome.get("type") != "welcome" or welcome.get("protocol") != PROTOCOL:
                raise ConnectionError("unsupported server protocol")
            self._send(stream, {
                "type": "join", "protocol": PROTOCOL, "name": self.name,
            })
            while True:
                line = stream.readline()
                if not line:
                    raise ConnectionError("server closed the connection")
                try:
                    message = decode(line)
                except ValueError as exc:
                    raise ConnectionError("invalid server message") from exc
                if not self.handle(message, lambda msg: self._send(stream, msg)):
                    return False
        finally:
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()
            with suppress(OSError):
                sock.close()

    @staticmethod
    def _expired(state):
        deadline = state.get("reply_by_ms")
        return (isinstance(deadline, (int, float))
                and not isinstance(deadline, bool)
                and time.time() * 1000 >= deadline)

    def handle(self, msg, send):
        message_type = msg.get("type")
        if message_type == "lobby":
            self.policy.on_lobby(msg)
        elif message_type == "start":
            self.player_id = msg.get("you")
            self.start_payload = msg
            self.expired_actions = []
            self.policy.on_start(msg)
        elif message_type == "state":
            me = find_player(msg, msg.get("you", self.player_id))
            if me is not None and me.get("alive", False):
                if self._expired(msg):
                    self.logger(f"turn {msg.get('turn')} already expired")
                    return True
                action = safe_decide(self.policy, msg)
                if action:
                    if self._expired(msg):
                        expired = {
                            "turn": msg.get("turn"), "action": action,
                            "reason": "turn_deadline_passed",
                        }
                        self.expired_actions.append(expired)
                        self.logger(f"turn {msg.get('turn')} action expired locally")
                    else:
                        send({"type": "action", "turn": msg["turn"],
                              "action": action})
        elif message_type == "end":
            self.policy.on_end(msg)
            return False
        elif message_type == "error":
            self.policy.on_error(msg)
        # joined, spectating, action_ack, pong, and unknown types are ignored.
        return True

    @staticmethod
    def _send(stream, msg):
        try:
            stream.write(encode(msg))
            stream.flush()
        except (OSError, ValueError) as exc:
            raise ConnectionError("could not send protocol message") from exc


def run_agent(host, port, name, policy, requeue=False, logger=print):
    client = ArenaClient(host, port, name, policy, requeue=requeue)
    if logger is not print:
        client.logger = logger
    client.run()


__all__ = ["ArenaClient", "run_agent"]
