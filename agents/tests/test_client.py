import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_agent.client import ArenaClient, run_agent
from arena_agent.policy import Policy, safe_decide
from arena_agent.render import render_board, summarize_event
from tools.spectator import run_replay


class RecordingPolicy(Policy):
    def __init__(self, action=None):
        self.calls = []
        self.action = action if action is not None else {"type": "wait"}

    def on_lobby(self, lobby):
        self.calls.append(("lobby", lobby))

    def on_start(self, start):
        self.calls.append(("start", start))

    def decide(self, state):
        self.calls.append(("state", state))
        return self.action

    def on_end(self, end):
        self.calls.append(("end", end))

    def on_error(self, error):
        self.calls.append(("error", error))


class ClientTests(unittest.TestCase):
    def test_callback_order_and_send(self):
        policy = RecordingPolicy()
        client = ArenaClient("127.0.0.1", 1, "A", policy,
                             logger=lambda *_: None)
        sent = []
        for msg in (
            {"type": "start", "you": "P1", "rules": {}, "players": []},
            {"type": "state", "turn": 1, "you": "P1", "players": [
                {"id": "P1", "alive": True}]},
            {"type": "end", "reason": "turn_limit"},
        ):
            client.handle(msg, sent.append)
        self.assertEqual([call[0] for call in policy.calls],
                         ["start", "state", "end"])
        self.assertEqual(sent, [{"type": "action", "turn": 1,
                                "action": {"type": "wait"}}])
        self.assertEqual(client.player_id, "P1")

    def test_lobby_error_and_unknown_messages(self):
        policy = RecordingPolicy()
        client = ArenaClient("h", 1, "A", policy, logger=lambda *_: None)
        sent = []
        messages = [
            {"type": "lobby", "players": []},
            {"type": "joined", "name": "A"},
            {"type": "action_ack", "turn": 1},
            {"type": "mystery"},
            {"type": "error", "code": "wall"},
        ]
        for message in messages:
            self.assertTrue(client.handle(message, sent.append))
        self.assertEqual([call[0] for call in policy.calls], ["lobby", "error"])
        self.assertEqual(sent, [])

    def test_dead_or_missing_player_does_not_decide(self):
        policy = RecordingPolicy()
        client = ArenaClient("h", 1, "A", policy, logger=lambda *_: None)
        sent = []
        client.handle({"type": "state", "turn": 1, "you": "P1",
                       "players": [{"id": "P1", "alive": False}]}, sent.append)
        client.handle({"type": "state", "turn": 2, "you": "P1",
                       "players": []}, sent.append)
        self.assertEqual(policy.calls, [])
        self.assertEqual(sent, [])

    def test_none_action_is_not_sent(self):
        policy = RecordingPolicy()
        policy.action = None
        client = ArenaClient("h", 1, "A", policy, logger=lambda *_: None)
        sent = []
        client.handle({"type": "state", "turn": 1, "you": "P1",
                       "players": [{"id": "P1", "alive": True}]}, sent.append)
        self.assertEqual(sent, [])

    def test_expired_turn_is_not_submitted(self):
        policy = RecordingPolicy()
        client = ArenaClient("h", 1, "A", policy, logger=lambda *_: None)
        sent = []
        client.handle({"type": "state", "turn": 1, "you": "P1",
                       "reply_by_ms": 1,
                       "players": [{"id": "P1", "alive": True}]}, sent.append)
        self.assertEqual(sent, [])

    def test_safe_decide_returns_wait_on_policy_error(self):
        class Broken(Policy):
            def decide(self, state):
                raise RuntimeError("boom")

        with patch("builtins.print") as printed:
            self.assertEqual(safe_decide(Broken(), {}), {"type": "wait"})
        self.assertIn("RuntimeError", printed.call_args.args[0])

    def test_connection_failure_backoff_then_clean_exit(self):
        client = ArenaClient("h", 1, "A", Policy(), logger=lambda *_: None)
        client.player_id = "OLD"
        client.start_payload = {"you": "OLD"}
        client.expired_actions = [{"turn": 7}]
        attempts = []

        def run_once():
            attempts.append((client.player_id, client.start_payload,
                             client.expired_actions))
            if len(attempts) == 1:
                raise ConnectionError("no")
            return False

        with patch.object(client, "_run_once", side_effect=run_once) as once, \
                patch("arena_agent.client.time.sleep") as sleep:
            client.run()
        self.assertEqual(once.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertEqual(attempts[1], (None, None, []))
        self.assertIsNone(client.player_id)
        self.assertIsNone(client.start_payload)
        self.assertEqual(client.expired_actions, [])

    def test_requeue_reconnects_after_end(self):
        class StopLoop(Exception):
            pass

        client = ArenaClient("h", 1, "A", Policy(), requeue=True,
                             logger=lambda *_: None)
        client.player_id = "OLD"
        client.start_payload = {"you": "OLD"}
        client.expired_actions = [{"turn": 7}]
        states = []

        def sleep(delay):
            states.append((client.player_id, client.start_payload,
                           client.expired_actions))
            if len(states) == 2:
                raise StopLoop

        with patch.object(client, "_run_once", side_effect=[False, False]) as once, \
                patch("arena_agent.client.time.sleep", side_effect=sleep) as sleep_mock:
            with self.assertRaises(StopLoop):
                client.run()
        self.assertEqual(once.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [1, 1])
        self.assertEqual(states, [(None, None, []), (None, None, [])])

    def test_send_writes_flushes_and_maps_socket_errors(self):
        stream = io.BytesIO()
        client = ArenaClient("h", 1, "A", Policy(), logger=lambda *_: None)
        client._send(stream, {"type": "ping"})
        self.assertEqual(stream.getvalue(), b'{"type":"ping"}\n')

        class Broken(io.BytesIO):
            def write(self, data):
                raise OSError("closed")

        with self.assertRaises(ConnectionError):
            client._send(Broken(), {"type": "ping"})

    def test_run_agent_uses_client(self):
        with patch("arena_agent.client.ArenaClient") as cls:
            run_agent("h", 2, "A", Policy(), requeue=True)
        cls.assert_called_once_with("h", 2, "A", unittest.mock.ANY,
                                    requeue=True)
        cls.return_value.run.assert_called_once_with()


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.start = {
            "mode": "king", "mode_state": {
                "zone": {"min": [6, 6], "max": [8, 8]},
            },
            "arena": {"width": 5, "height": 4, "walls": [[2, 1]]},
        }
        self.state = {
            "turn": 3, "turn_limit": 10, "mode": "king",
            "mode_state": {"zone": {"min": [6, 6], "max": [8, 8]}},
            "players": [
                {"id": "P1", "name": "Alpha", "pos": [1, 1], "hp": 80,
                 "energy": 42, "shield": 5, "score": 12, "alive": True,
                 "hill_streak": 2},
                {"id": "P2", "name": "another", "pos": [3, 1], "hp": 60,
                 "energy": 20, "shield": 0, "score": 4, "alive": True},
            ],
            "nodes": [
                {"pos": [1, 2], "cooldown": 0, "active": True},
                {"pos": [3, 2], "cooldown": 2, "active": False},
            ],
            "events": [{"type": "hill_score", "player": "P1", "points": 7}],
        }

    def test_board_symbols_status_and_mode(self):
        text = render_board(self.start, self.state, color=False)
        self.assertIn("King of the Hill", text)
        self.assertIn("P1", text)
        self.assertIn("HP 80", text)
        self.assertIn("Energy 42", text)
        self.assertIn("Shield 5", text)
        self.assertIn("Score 12", text)
        self.assertIn("#", text)
        self.assertIn("*", text)
        self.assertIn("o", text)
        self.assertIn("zone=[6,6]-[8,8]", text)
        self.assertNotIn("\x1b[", text)

    def test_duplicate_initials_use_player_ids(self):
        self.state["players"][1]["name"] = "Apex"
        text = render_board(self.start, self.state, color=False)
        self.assertIn("P1", text)
        self.assertIn("P2", text)

    def test_color_and_malformed_regions_do_not_crash(self):
        self.assertIn("\x1b[", render_board(self.start, self.state, color=True))
        broken = dict(self.state)
        broken["mode_state"] = {"zone": "not drawable"}
        broken["players"] = [{"id": "P1", "name": "A", "pos": [99, 99]}]
        broken["nodes"] = [{"pos": "bad"}]
        text = render_board(self.start, broken, color=False)
        self.assertIn("zone=unavailable", text)

    def test_event_summaries_include_new_modes_and_unknown_events(self):
        expected = {
            "hill_score": "Hill", "storm_shrink": "Storm",
            "storm_damage": "Storm", "bounty_complete": "Bounty",
            "bounty_retarget": "Bounty", "friendly_blocked": "Friendly",
        }
        for event_type, needle in expected.items():
            with self.subTest(event_type=event_type):
                self.assertIn(needle, summarize_event({"type": event_type}))
        unknown = summarize_event({"type": "future_event", "value": 3})
        self.assertIn("future_event", unknown)
        self.assertIn("3", unknown)


class BotCliTests(unittest.TestCase):
    def test_module_entry_points_have_no_runpy_warnings(self):
        root = Path(__file__).resolve().parents[1]
        for module in ("bots.random_bot", "bots.heuristic", "bots.llm_agent"):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-m", module, "--help"], cwd=root,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("RuntimeWarning", result.stderr)


class SpectatorTests(unittest.TestCase):
    def make_replay(self, directory):
        path = Path(directory) / "match.jsonl"
        records = [
            {"type": "start", "mode": "bounty", "mode_state": {},
             "arena": {"width": 3, "height": 3, "walls": []}},
            {"type": "state", "turn": 1, "mode": "bounty",
             "mode_state": {}, "players": [], "nodes": [],
             "events": [{"type": "bounty_retarget", "player": "P1",
                         "target": "P2"}]},
            {"type": "end", "reason": "turn_limit", "winner": None,
             "standings": []},
        ]
        path.write_text("".join(json.dumps(row) + "\n" for row in records),
                        encoding="utf-8")
        return path

    def test_replay_renders_events_and_end_without_network_or_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_replay(directory)
            output = []
            with patch("tools.spectator.os.system") as clear, \
                    patch("tools.spectator.socket.create_connection") as connect:
                run_replay(path, delay=0, color=False, plain=True,
                           output=output.append)
            clear.assert_not_called()
            connect.assert_not_called()
        text = "\n".join(output)
        self.assertIn("Bounty", text)
        self.assertIn("Bounty retarget", text)
        self.assertIn("turn_limit", text)

    def test_replay_delay_zero_never_sleeps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_replay(directory)
            with patch("tools.spectator.time.sleep") as sleep:
                run_replay(path, delay=0, color=False, plain=True,
                           output=lambda *_: None)
            sleep.assert_not_called()

    def test_plain_replay_contains_no_ansi(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_replay(directory)
            output = []
            run_replay(path, delay=0, color=False, plain=True,
                       output=output.append)
        self.assertNotIn("\x1b[", "\n".join(output))


if __name__ == "__main__":
    unittest.main()
