import unittest

from arena_server.config import Rules
from arena_server.engine import Engine, MapData, NODE_POINTS


class ModeFrameworkTests(unittest.TestCase):
    def test_classic_default_and_payload_compatibility(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")], seed=1,
                   map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        self.assertEqual(e.mode_name, "classic")
        self.assertEqual(e.mode_state, {})
        self.assertEqual(e.start_payload()["mode"], "classic")
        self.assertNotIn("hill_streak", e.state_payload()["players"][0])


class KingModeTests(unittest.TestCase):
    def make(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")], seed=1,
                   map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="king")
        e.players["P1"].pos = (7, 7)
        e.players["P2"].pos = (1, 1)
        return e

    def test_zone_score_and_streak(self):
        e = self.make()
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 5)
        self.assertEqual(e.mode_state["streaks"]["P1"], 1)
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 11)
        self.assertEqual(e.mode_state["streaks"]["P1"], 2)
        self.assertIn({"type": "hill_score", "player": "P1", "pos": [7, 7],
                       "points": 6, "streak": 2, "score": 11}, e.last_events)

    def test_leaving_zone_resets_streak(self):
        e = self.make()
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        e.players["P1"].pos = (5, 5)
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 5)
        self.assertEqual(e.mode_state["streaks"]["P1"], 0)

    def test_forfeit_immediately_resets_hill_streak(self):
        e = self.make()
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.mode_state["streaks"]["P1"], 1)
        self.assertTrue(e.forfeit("P1"))
        current = next(p for p in e.state_payload()["players"]
                       if p["id"] == "P1")
        final = next(p for p in e.end_payload()["standings"]
                     if p["id"] == "P1")
        self.assertEqual(current["hill_streak"], 0)
        self.assertEqual(final["hill_streak"], 0)

    def test_target_score_ends_match(self):
        e = self.make()
        e.players["P1"].score = 95
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_reason, "score_limit")
        self.assertEqual(e.end_payload()["winner"]["id"], "P1")


if __name__ == "__main__":
    unittest.main()
