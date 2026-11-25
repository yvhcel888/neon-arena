import copy
import io
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from arena_agent.policy import Policy, legal_actions
from bots.heuristic import HeuristicPolicy
from bots.llm_agent import LlmPolicy, parse_action


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def completion(text):
    return FakeResponse(json.dumps({
        "choices": [{"message": {"content": text}}],
    }).encode("utf-8"))


class LlmTests(unittest.TestCase):
    def test_extract_json_action(self):
        text = 'thinking... {"type": "attack", "dir": "e"} done'
        self.assertEqual(parse_action(text), {"type": "attack", "dir": "e"})

    def test_reject_non_action(self):
        self.assertIsNone(parse_action("I will attack"))
        self.assertIsNone(parse_action('{"type": "fly"}'))
        self.assertIsNone(parse_action('{"type": "move", "dir": "up"}'))

    def test_accepts_each_action_and_rejects_bad_shapes(self):
        for action in ({"type": "wait"}, {"type": "gather"},
                       {"type": "move", "dir": "n"},
                       {"type": "dash", "dir": "w"},
                       {"type": "heal"}, {"type": "shield"}):
            with self.subTest(action=action):
                self.assertEqual(parse_action(json.dumps(action)), action)
        for text in ('[]', '{"type": "attack"}', '{"type": 1}',
                     '{"type": "move", "dir": null}'):
            with self.subTest(text=text):
                self.assertIsNone(parse_action(text))


class FixedFallback(Policy):
    def __init__(self, action):
        self.action = action
        self.starts = []
        self.calls = []

    def on_start(self, start):
        self.starts.append(start)

    def decide(self, state):
        self.calls.append(state)
        return dict(self.action)


class LlmPolicyTests(unittest.TestCase):
    def setUp(self):
        self.start = {
            "you": "P1", "mode": "bounty",
            "mode_state": {"target_score": 150, "targets": {"P1": "P2"}},
            "tick_ms": 1000,
            "rules": {"attack": {"cost": 8}, "max_hp": 100},
            "arena": {"width": 15, "height": 15, "walls": []},
            "players": [{"id": "P1", "name": "A"}],
        }
        self.state = {
            "turn": 1, "you": "P1", "mode": "bounty",
            "mode_state": {"target_score": 150, "targets": {"P1": "P2"}},
            "players": [
                {"id": "P1", "pos": [1, 1], "hp": 100, "energy": 80,
                 "shield": 0, "alive": True, "bounty_target": "P2"},
                {"id": "P2", "pos": [3, 1], "hp": 90, "energy": 60,
                 "shield": 0, "alive": True},
            ],
            "nodes": [{"pos": [7, 7], "active": True, "cooldown": 0}],
            "events": [{"type": "bounty_retarget", "player": "P1",
                        "target": "P2"}],
        }

    def test_prompt_contains_geometry_and_exact_visible_legal_actions(self):
        self.start["arena"]["walls"] = [[2, 1]]
        policy = LlmPolicy(fallback=False, logger=lambda *_: None)
        policy.on_start(self.start)
        prompt = policy.build_prompt(self.state)
        payload = json.loads(prompt.split("\n", 1)[1])
        self.assertEqual(payload["arena"], {
            "width": 15, "height": 15, "walls": [[2, 1]],
        })
        self.assertEqual(payload["legal_actions"],
                         legal_actions(self.start, self.state, "P1"))
        self.assertNotIn({"type": "move", "dir": "e"},
                         payload["legal_actions"])
        self.assertIn("bounty", prompt)
        self.assertIn("target_score", prompt)
        self.assertIn("P2", prompt)
        self.assertIn("nodes", prompt)
        self.assertIn("bounty_retarget", prompt)
        self.assertIn("shared decision window", prompt)

    def test_illegal_model_actions_use_fallback(self):
        full_hp = copy.deepcopy(self.state)
        full_shield = copy.deepcopy(self.state)
        full_shield["players"][0]["shield"] = 40
        no_energy = copy.deepcopy(self.state)
        no_energy["players"][0]["energy"] = 0
        occupied = copy.deepcopy(self.state)
        occupied["players"].append({
            "id": "P3", "pos": [2, 1], "hp": 100,
            "energy": 80, "shield": 0, "alive": True,
        })
        cases = [
            ("border wall move", self.state, {"type": "move", "dir": "w"}),
            ("gather off node", self.state, {"type": "gather"}),
            ("heal at full hp", full_hp, {"type": "heal"}),
            ("shield at full", full_shield, {"type": "shield"}),
            ("dash without energy", no_energy, {"type": "dash", "dir": "e"}),
            ("occupied move", occupied, {"type": "move", "dir": "e"}),
        ]
        for name, snapshot, action in cases:
            with self.subTest(case=name):
                self.assertNotIn(action,
                                 legal_actions(self.start, snapshot, "P1"))
                fallback = FixedFallback({"type": "heal"})
                policy = LlmPolicy(
                    fallback_policy=fallback, logger=lambda *_: None,
                    opener=lambda *args, **kwargs: completion(json.dumps(action)),
                )
                policy.on_start(self.start)
                self.assertEqual(policy.decide(snapshot), {"type": "heal"})
                self.assertEqual(fallback.calls, [snapshot])

    def test_illegal_model_action_without_fallback_waits(self):
        policy = LlmPolicy(
            fallback=False, logger=lambda *_: None,
            opener=lambda *args, **kwargs: completion('{"type":"gather"}'),
        )
        policy.on_start(self.start)
        self.assertEqual(policy.decide(self.state), {"type": "wait"})

    def test_request_uses_env_configuration_and_tick_bounded_timeout(self):
        now = [100.0]
        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            now[0] += 0.05
            return completion('{"type":"wait"}')

        env = {
            "NEON_ARENA_LLM_BASE_URL": "http://example.invalid/v1",
            "NEON_ARENA_LLM_MODEL": "test-model",
            "NEON_ARENA_LLM_API_KEY": "secret-key",
            "NEON_ARENA_LLM_TIMEOUT_MS": "9000",
        }
        with patch.dict(os.environ, env, clear=False):
            policy = LlmPolicy(fallback=False, logger=lambda *_: None,
                               opener=opener, clock=lambda: now[0])
            policy.on_start(self.start)
            self.assertLess(policy.timeout_ms, self.start["tick_ms"])
            snapshot = dict(self.state, reply_by_ms=int(now[0] * 1000) + 1000)
            self.assertEqual(policy.decide(snapshot), {"type": "wait"})
        request, timeout = captured[0]
        self.assertEqual(request.full_url, "http://example.invalid/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "test-model")
        self.assertGreater(timeout, 0)
        self.assertLess(timeout, 1.0)

    def test_parse_failure_uses_heuristic_fallback(self):
        fallback = FixedFallback({"type": "heal"})
        policy = LlmPolicy(fallback_policy=fallback, logger=lambda *_: None,
                           opener=lambda *args, **kwargs: completion("no json"))
        policy.on_start(self.start)
        self.assertEqual(policy.decide(self.state), {"type": "heal"})
        self.assertEqual(fallback.starts, [self.start])

    def test_no_fallback_returns_wait(self):
        policy = LlmPolicy(fallback=False, logger=lambda *_: None,
                           opener=lambda *args, **kwargs: completion("no json"))
        policy.on_start(self.start)
        self.assertEqual(policy.decide(self.state), {"type": "wait"})

    def test_timeout_uses_fallback_without_leaking_key(self):
        fallback = FixedFallback({"type": "gather"})

        def timeout(*args, **kwargs):
            raise TimeoutError("secret-key must not appear")

        output = []
        with patch.dict(os.environ, {"NEON_ARENA_LLM_API_KEY": "secret-key"}):
            policy = LlmPolicy(fallback_policy=fallback,
                               logger=output.append, opener=timeout)
            policy.on_start(self.start)
            self.assertEqual(policy.decide(self.state), {"type": "gather"})
        self.assertNotIn("secret-key", "\n".join(output))

    def test_blocking_opener_is_bounded_and_later_turn_does_not_overlap(self):
        started = threading.Event()
        release = threading.Event()
        calls = []
        active = [0]
        max_active = [0]

        def blocking_opener(request, timeout):
            calls.append((request, timeout))
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
            started.set()
            try:
                release.wait(2)
                return completion('{"type":"wait"}')
            finally:
                active[0] -= 1

        fallback = FixedFallback({"type": "heal"})
        policy = LlmPolicy(fallback_policy=fallback, logger=lambda *_: None,
                           opener=blocking_opener)
        policy.on_start(self.start)
        first = dict(self.state, turn=1,
                     reply_by_ms=int(time.time() * 1000) + 500)
        second = dict(self.state, turn=2,
                      reply_by_ms=int(time.time() * 1000) + 1000)
        try:
            before = time.monotonic()
            self.assertEqual(policy.decide(first), {"type": "heal"})
            first_elapsed = time.monotonic() - before
            self.assertTrue(started.wait(1))

            before = time.monotonic()
            self.assertEqual(policy.decide(second), {"type": "heal"})
            second_elapsed = time.monotonic() - before
        finally:
            release.set()
            worker = getattr(policy, "_request_thread", None)
            if worker is not None:
                worker.join(timeout=2)

        self.assertLess(first_elapsed, 0.75)
        self.assertLess(second_elapsed, 0.25)
        self.assertEqual(len(calls), 1)
        self.assertEqual(max_active, [1])
        self.assertEqual(len(fallback.calls), 2)

    def test_busy_policy_without_fallback_waits_immediately(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def blocking_opener(request, timeout):
            calls.append((request, timeout))
            started.set()
            release.wait(2)
            return completion('{"type":"wait"}')

        policy = LlmPolicy(fallback=False, logger=lambda *_: None,
                           opener=blocking_opener)
        policy.on_start(self.start)
        try:
            first = dict(self.state, turn=1,
                         reply_by_ms=int(time.time() * 1000) + 500)
            second = dict(self.state, turn=2,
                          reply_by_ms=int(time.time() * 1000) + 1000)
            self.assertEqual(policy.decide(first), {"type": "wait"})
            self.assertTrue(started.wait(1))
            before = time.monotonic()
            self.assertEqual(policy.decide(second), {"type": "wait"})
            elapsed = time.monotonic() - before
        finally:
            release.set()
            worker = getattr(policy, "_request_thread", None)
            if worker is not None:
                worker.join(timeout=2)

        self.assertLess(elapsed, 0.25)
        self.assertEqual(len(calls), 1)

    def test_action_after_deadline_is_only_recorded_as_expired(self):
        now = [100.0]
        fallback = FixedFallback({"type": "heal"})

        def late(request, timeout):
            now[0] += 2.0
            return completion('{"type":"attack","dir":"e"}')

        policy = LlmPolicy(fallback_policy=fallback, logger=lambda *_: None,
                           opener=late, clock=lambda: now[0])
        policy.on_start(self.start)
        snapshot = dict(self.state, reply_by_ms=100500)
        self.assertIsNone(policy.decide(snapshot))
        self.assertEqual(policy.expired_actions[0]["turn"], 1)
        self.assertEqual(policy.expired_actions[0]["action"],
                         {"type": "attack", "dir": "e"})
        self.assertEqual(policy.expired_actions[0]["reason"],
                         "turn_deadline_passed")

    def test_already_expired_turn_does_not_call_llm(self):
        calls = []
        policy = LlmPolicy(fallback_policy=FixedFallback({"type": "heal"}),
                           logger=lambda *_: None,
                           opener=lambda *args, **kwargs: calls.append(args))
        policy.on_start(self.start)
        snapshot = dict(self.state, reply_by_ms=1)
        self.assertIsNone(policy.decide(snapshot))
        self.assertEqual(calls, [])
        self.assertEqual(policy.expired_actions[0]["action"], {"type": "heal"})

    def test_default_fallback_is_heuristic(self):
        policy = LlmPolicy(logger=lambda *_: None,
                           opener=lambda *args, **kwargs: completion("bad"))
        policy.on_start(self.start)
        action = policy.decide(self.state)
        self.assertIn(action["type"],
                      {"move", "dash", "attack", "gather", "heal",
                       "shield", "wait"})
        self.assertIsInstance(policy.fallback, HeuristicPolicy)


if __name__ == "__main__":
    unittest.main()
