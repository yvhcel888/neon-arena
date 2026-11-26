"""Cross-process acceptance tests for the real server, agents, and HTTP API."""

from __future__ import annotations

import json
import queue
import select
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
AGENTS_DIR = ROOT / "agents"
SCRIPTS_DIR = ROOT / "scripts"


def free_ports(count=2):
    """Reserve distinct loopback ports together before releasing them."""
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def http_json(base, method, path, body=None, token=None, timeout=3):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, resp.headers.get_content_type(), json.loads(
                raw or b"{}",
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return (
            exc.code,
            exc.headers.get_content_type(),
            json.loads(raw) if raw else {},
        )


class RawTCPObserver:
    """Slot-free NDJSON spectator that records unmodified TCP wire messages."""

    def __init__(self, host, port):
        self.messages = []
        self._incoming = queue.Queue()
        self._stop = threading.Event()
        self._error = None
        self._buffer = b""
        self._sock = socket.create_connection((host, port), timeout=3)
        self._sock.settimeout(0.2)
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        try:
            self._send({"type": "spectate"})
            welcome = self.wait_for("welcome")
            if welcome.get("protocol") != 1:
                raise ConnectionError(f"unsupported TCP protocol: {welcome}")
            subscription = self.wait_for("spectating")
            if subscription.get("match_running") is not False:
                raise ConnectionError(
                    "observer must subscribe before the King match starts",
                )
        except Exception:
            self.close()
            raise

    def _send(self, message):
        self._sock.sendall(json.dumps(message).encode("utf-8") + b"\n")

    def _read_loop(self):
        try:
            while not self._stop.is_set():
                readable, _, _ = select.select([self._sock], [], [], 0.2)
                if not readable:
                    continue
                chunk = self._sock.recv(65536)
                if not chunk:
                    raise ConnectionError("server closed the raw TCP observer")
                self._buffer += chunk
                while b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    message = json.loads(line.decode("utf-8"))
                    if not isinstance(message, dict):
                        raise ConnectionError("TCP message was not a JSON object")
                    self._incoming.put(message)
        except Exception as exc:
            if not self._stop.is_set():
                self._error = exc

    def wait_for(self, message_type, timeout=10):
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = self._incoming.get(timeout=0.1)
            except queue.Empty:
                if self._error is not None:
                    raise ConnectionError("raw TCP observer failed") from self._error
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"raw TCP observer did not receive {message_type!r}",
                    )
                continue
            self.messages.append(message)
            if message.get("type") == message_type:
                return message

    def close(self):
        self._stop.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._thread.join(timeout=2)
        self._sock.close()
        if self._thread.is_alive():
            raise RuntimeError("raw TCP observer thread did not stop")


class EndToEndTests(unittest.TestCase):
    max_message_length = 4096

    def setUp(self):
        self.procs = []
        self.bots = []
        self.server = None
        self.tcp_observer = None
        self.tcp_port, self.api_port = free_ports(2)
        self.base = f"http://127.0.0.1:{self.api_port}/api/v1"
        self.root_url = f"http://127.0.0.1:{self.api_port}"
        self.token = None

    def tearDown(self):
        try:
            if self.tcp_observer is not None:
                self.tcp_observer.close()
        finally:
            # Bots are appended after the server, so reverse order also satisfies
            # the required "clients first, server last" shutdown order.
            for proc in reversed(self.procs):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
        self.assertFalse(
            any(proc.poll() is None for proc in self.procs),
            "a child process survived E2E cleanup",
        )

    def start(self, args, cwd, quiet=True):
        kwargs = {
            "cwd": str(cwd),
            "stdout": subprocess.DEVNULL if quiet else subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        proc = subprocess.Popen([sys.executable, *args], **kwargs)
        self.procs.append(proc)
        return proc

    def start_server(self, mode, min_players):
        self.server = self.start([
            "-m", "arena_server",
            "--host", "127.0.0.1",
            "--tcp-port", str(self.tcp_port),
            "--api-port", str(self.api_port),
            "--mode", mode,
            "--tick-ms", "300",
            "--min-turn-ms", "0",
            "--turn-limit", "3",
            "--min-players", str(min_players),
            "--max-players", "4",
            "--lobby-wait-ms", "100",
            "--seed", "10",
            "--no-logs",
        ], SERVER_DIR, quiet=False)
        self.wait_health()

    def wait_health(self, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                output = self.server.communicate(timeout=5)[0]
                self.fail(f"server exited early:\n{output}")
            try:
                status, content_type, data = http_json(
                    self.base, "GET", "/health",
                )
                if status == 200 and data.get("ok"):
                    self.assertEqual(content_type, "application/json")
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.05)
        self.fail("server health check timed out")

    def create_human(self):
        status, _, data = http_json(
            self.base, "POST", "/sessions", body={"name": "Human"},
        )
        self.assertEqual(status, 200, data)
        self.token = data["token"]

    def start_bot(self, name):
        proc = self.start([
            "-m", "bots.random_bot",
            "--host", "127.0.0.1",
            "--port", str(self.tcp_port),
            "--name", name,
            "--quiet",
        ], AGENTS_DIR)
        self.bots.append(proc)
        return proc

    def play_as_human(self, expected_mode):
        """Poll the HTTP view, submit legal waits, and return the final view."""
        view = None
        saw_start_and_state = False
        successful_http_action = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            status, _, data = http_json(
                self.base, "GET", "/state", token=self.token,
            )
            self.assertEqual(status, 200, data)
            view = data["view"]
            self.assertEqual(view["you"]["name"], "Human")
            if view["mode"] == "lobby":
                self.assertEqual(view["lobby"]["mode"], expected_mode)
            elif view["mode"] == "match":
                match = view["match"]
                # The HTTP match view combines start fields (arena/rules) and
                # state fields (turn/players). Both must carry the same mode.
                self.assertEqual(match["mode"], expected_mode)
                self.assertIn("arena", match)
                self.assertIn("turn", match)
                saw_start_and_state = True
                self.assertEqual(
                    {player["kind"] for player in match["players"]},
                    {"agent", "human"},
                )
                if not match["submitted"]:
                    status, _, action_data = http_json(
                        self.base, "POST", "/actions", token=self.token,
                        body={
                            "turn": match["turn"],
                            "action": {"type": "wait"},
                        },
                    )
                    if status == 200:
                        self.assertTrue(action_data.get("ok"), action_data)
                        self.assertEqual(action_data.get("turn"), match["turn"])
                        self.assertEqual(
                            action_data.get("action"), {"type": "wait"},
                        )
                        successful_http_action = True
                    elif status == 409 and successful_http_action:
                        # A stale-turn retry is acceptable only after a real
                        # action has succeeded in this match.
                        pass
                    else:
                        self.fail(
                            "human action failed before/without a successful "
                            f"HTTP 200 action: status={status}, data={action_data}",
                        )
            elif view["mode"] == "ended":
                self.assertTrue(
                    successful_http_action,
                    "match ended without a successful human HTTP action (200)",
                )
                self.assertTrue(saw_start_and_state)
                self.assertEqual(view["result"]["mode"], expected_mode)
                return view
            else:
                self.fail(f"unexpected view mode: {view['mode']}")
            time.sleep(0.05)
        self.fail(f"{expected_mode} match did not finish; last view={view}")

    def assert_bots_exited(self):
        deadline = time.monotonic() + 10
        for proc in self.bots:
            remaining = max(0, deadline - time.monotonic())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                self.fail(f"bot {proc.args} did not exit after match end")
            self.assertEqual(proc.returncode, 0, proc.args)

    def assert_http_is_json_only(self):
        for path in ("/", "/index.html", "/client/app.js", "/client/style.css"):
            status, content_type, data = http_json(self.root_url, "GET", path)
            self.assertEqual(status, 404, path)
            self.assertEqual(content_type, "application/json", path)
            self.assertFalse(data["ok"], path)
        status, content_type, data = http_json(self.base, "GET", "/")
        self.assertEqual(status, 404)
        self.assertEqual(content_type, "application/json")
        self.assertFalse(data["ok"])

    def stop_server(self):
        self.assertIsNotNone(self.server)
        if self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
        self.assertIsNotNone(
            self.server.returncode,
            "server did not exit after termination",
        )
        output = self.server.communicate(timeout=5)[0]
        self.assertNotIn("Traceback", output)

    def test_human_conflict_before_success_is_rejected(self):
        """A 409 is only a retry after this human has received a 200."""
        case = EndToEndTests("test_human_conflict_before_success_is_rejected")
        case.base = "http://unused"
        case.token = "unused"
        match_view = {
            "mode": "match",
            "you": {"name": "Human"},
            "match": {
                "mode": "classic", "turn": 1, "submitted": False,
                "arena": {}, "rules": {},
                "players": [{"kind": "human"}, {"kind": "agent"}],
            },
        }
        responses = [
            (200, "application/json", {"view": match_view}),
            (409, "application/json", {"ok": False, "error": "stale_turn"}),
            (200, "application/json", {"view": {"mode": "ended"}}),
        ]
        with patch.object(sys.modules[__name__], "http_json",
                          side_effect=responses), \
                patch.object(sys.modules[__name__].time, "sleep"):
            with self.assertRaisesRegex(
                AssertionError, "successful HTTP 200 action",
            ):
                case.play_as_human("classic")

    def test_human_and_agents_finish_real_match(self):
        self.start_server("classic", min_players=3)
        self.create_human()

        # Queue the human first so the two agents cannot start without them.
        for name in ("BotA", "BotB"):
            self.start_bot(name)

        view = self.play_as_human("classic")
        result = view["result"]
        self.assertIn(
            result["reason"],
            {"last_standing", "turn_limit", "mutual_destruction",
             "score_limit"},
        )
        self.assertEqual(len(result["standings"]), 3)
        self.assertEqual(
            {row["name"] for row in result["standings"]},
            {"Human", "BotA", "BotB"},
        )
        self.assert_bots_exited()
        self.assert_http_is_json_only()
        self.stop_server()

    def assert_king_tcp_wire_messages(self, observer):
        observer.wait_for("end")
        starts = [msg for msg in observer.messages if msg.get("type") == "start"]
        states = [msg for msg in observer.messages if msg.get("type") == "state"]
        ends = [msg for msg in observer.messages if msg.get("type") == "end"]
        self.assertEqual(len(starts), 1, observer.messages)
        self.assertGreaterEqual(len(states), 1, observer.messages)
        self.assertEqual(len(ends), 1, observer.messages)

        start = starts[0]
        self.assertEqual(start["protocol"], 1)
        self.assertEqual(start["mode"], "king")
        self.assertNotIn("you", start, "observer must remain a spectator")
        self.assertIn("arena", start)
        for field in ("width", "height", "walls", "nodes", "spawns"):
            self.assertIn(field, start["arena"])
        self.assertIn("max_hp", start["rules"])
        self.assertEqual(
            {player["name"] for player in start["players"]},
            {"Human", "BotA", "BotB"},
        )
        self.assertEqual(
            {player["kind"] for player in start["players"]},
            {"human", "agent"},
        )
        start_mode_state = start["mode_state"]
        self.assertEqual(start_mode_state["target_score"], 100)
        self.assertIn("zone", start_mode_state)
        self.assertEqual(
            set(start_mode_state["streaks"]),
            {player["id"] for player in start["players"]},
        )

        for state in states:
            self.assertEqual(state["match_id"], start["match_id"])
            self.assertEqual(state["mode"], "king")
            self.assertNotIn("you", state)
            self.assertGreaterEqual(state["turn"], 1)
            self.assertIn("nodes", state)
            self.assertIn("events", state)
            self.assertEqual(state["mode_state"]["zone"],
                             start_mode_state["zone"])
            self.assertEqual(
                {player["name"] for player in state["players"]},
                {"Human", "BotA", "BotB"},
            )
            for player in state["players"]:
                self.assertIn("hill_streak", player)
                self.assertIsInstance(player["hill_streak"], int)

        end = ends[0]
        self.assertEqual(end["match_id"], start["match_id"])
        self.assertEqual(end["mode"], "king")
        self.assertEqual(
            {player["name"] for player in end["standings"]},
            {"Human", "BotA", "BotB"},
        )

    def test_king_mode_human_and_agents_finish(self):
        self.start_server("king", min_players=3)
        # Subscribe before any player joins so start/state are observed directly
        # from TCP without consuming a fourth player slot.
        self.tcp_observer = RawTCPObserver("127.0.0.1", self.tcp_port)
        self.create_human()
        for name in ("BotA", "BotB"):
            self.start_bot(name)

        view = self.play_as_human("king")
        self.assert_king_tcp_wire_messages(self.tcp_observer)
        result = view["result"]
        self.assertEqual(result["mode"], "king")
        self.assertEqual(len(result["standings"]), 3)
        self.assertEqual(
            {row["name"] for row in result["standings"]},
            {"Human", "BotA", "BotB"},
        )
        self.assert_bots_exited()
        self.assert_http_is_json_only()
        self.stop_server()

    def test_team_mode_four_participants_finish(self):
        self.start_server("team", min_players=4)
        self.create_human()
        for name in ("BotA", "BotB", "BotC"):
            self.start_bot(name)

        view = self.play_as_human("team")
        match = view["match"]
        self.assertEqual(match["mode"], "team")
        self.assertEqual(len(match["players"]), 4)
        self.assertEqual(
            {player["name"] for player in match["players"]},
            {"Human", "BotA", "BotB", "BotC"},
        )
        teams = {}
        for player in match["players"]:
            teams.setdefault(player["team"], []).append(player["name"])
        self.assertEqual(set(teams), {"T1", "T2"})
        self.assertEqual(sorted(len(members) for members in teams.values()), [2, 2])

        result = view["result"]
        self.assertEqual(result["mode"], "team")
        self.assertEqual(len(result["standings"]), 4)
        self.assertEqual(len(result["team_standings"]), 2)
        self.assertEqual(
            {row["id"] for row in result["team_standings"]}, {"T1", "T2"},
        )
        for row in result["team_standings"]:
            self.assertEqual(len(row["members"]), 2)
        self.assertEqual(result["winner"]["kind"], "team")
        self.assertIn(result["winner"]["id"], {"T1", "T2"})
        self.assert_bots_exited()
        self.assert_http_is_json_only()
        self.stop_server()


if __name__ == "__main__":
    unittest.main()
