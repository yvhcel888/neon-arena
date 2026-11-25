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

    def test_death_resets_hill_streak(self):
        e = self.make()
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.mode_state["streaks"]["P1"], 1)

        e.players["P1"].hp = Rules().attack_damage
        e.players["P2"].pos = (7, 8)
        e.players["P2"].energy = 50
        e.resolve({"P1": {"type": "wait"},
                   "P2": {"type": "attack", "dir": "n"}})

        self.assertFalse(e.players["P1"].alive)
        self.assertEqual(e.mode_state["streaks"]["P1"], 0)
        self.assertFalse(any(event["type"] == "hill_score"
                             and event["player"] == "P1"
                             for event in e.last_events))

    def test_streak_bonus_caps_at_five_per_turn(self):
        e = self.make()
        expected_points = (5, 6, 7, 8, 9, 10, 10)
        expected_score = 0
        for turn, points in enumerate(expected_points, start=1):
            with self.subTest(turn=turn):
                e.resolve({"P1": {"type": "wait"},
                           "P2": {"type": "wait"}})
                expected_score += points
                self.assertEqual(e.players["P1"].score, expected_score)
                self.assertEqual(e.last_events[-1]["points"], points)

    def test_zone_includes_six_and_eight_but_not_five_or_nine(self):
        cases = (
            ((6, 6), True),
            ((6, 8), True),
            ((8, 6), True),
            ((8, 8), True),
            ((5, 7), False),
            ((9, 7), False),
            ((7, 5), False),
            ((7, 9), False),
        )
        for pos, in_zone in cases:
            with self.subTest(pos=pos):
                e = self.make()
                e.players["P1"].pos = pos
                e.resolve({"P1": {"type": "wait"},
                           "P2": {"type": "wait"}})
                self.assertEqual(e.players["P1"].score, 5 if in_zone else 0)
                self.assertEqual(e.mode_state["streaks"]["P1"],
                                 1 if in_zone else 0)
                hill_events = [event for event in e.last_events
                               if event["type"] == "hill_score"]
                self.assertEqual(len(hill_events), 1 if in_zone else 0)

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

    def test_score_limit_ends_when_target_scorer_dies_with_others_alive(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent"),
                             ("C", "agent"), ("D", "agent")], seed=1,
                   map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="king")
        e.players["P1"].pos = (6, 6)
        e.players["P2"].pos = (7, 6)
        e.players["P3"].pos = (1, 1)
        e.players["P4"].pos = (13, 13)
        e.players["P1"].hp = Rules().attack_damage
        e.players["P1"].score = 95
        e.players["P1"].energy = 50
        e.players["P2"].energy = 50
        e.mode_state["streaks"]["P1"] = 3

        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "attack", "dir": "w"},
            "P3": {"type": "wait"},
            "P4": {"type": "wait"},
        })

        self.assertGreaterEqual(e.players["P1"].score,
                                e.mode_state["target_score"])
        self.assertFalse(e.players["P1"].alive)
        self.assertGreaterEqual(sum(p.alive for p in e.players.values()), 3)
        self.assertIn({"type": "death", "player": "P1", "killer": "P2"},
                      e.last_events)
        self.assertEqual(e.mode_state["streaks"]["P1"], 0)
        self.assertTrue(e.finished)
        self.assertEqual(e.end_reason, "score_limit")

    def test_target_score_ends_match(self):
        e = self.make()
        e.players["P1"].score = 95
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_reason, "score_limit")
        self.assertEqual(e.end_payload()["winner"]["id"], "P1")


class TeamModeTests(unittest.TestCase):
    def make(self):
        e = Engine(Rules(), [("A", "human"), ("B", "agent"),
                             ("C", "human"), ("D", "agent")],
                   seed=2, map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="team")
        for pid, pos in {"P1": (5, 5), "P2": (5, 7),
                         "P3": (6, 5), "P4": (9, 9)}.items():
            e.players[pid].pos = pos
            e.players[pid].energy = 50
        return e

    def test_teams_and_friendly_fire(self):
        e = self.make()
        self.assertEqual(e.state_payload()["players"][0]["team"], "T1")
        self.assertEqual(e.state_payload()["players"][2]["team"], "T2")
        e.players["P2"].pos = (6, 5)
        e.players["P2"].shield = 13
        e.players["P3"].pos = (8, 5)
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"},
                   "P4": {"type": "wait"}})
        self.assertEqual(e.players["P2"].hp, 100)
        self.assertEqual(e.players["P2"].shield, 13)
        self.assertEqual(e.players["P1"].score, 0)
        self.assertEqual(e.players["P1"].energy, 46)
        self.assertIn({"type": "friendly_blocked", "player": "P1",
                       "target": "P2"}, e.last_events)
        self.assertFalse(any(event["type"] == "damage"
                             for event in e.last_events))

    def test_enemy_damage_scores_and_team_total_updates(self):
        e = self.make()
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"},
                   "P4": {"type": "wait"}})
        self.assertEqual(e.players["P3"].hp, 78)
        self.assertEqual(e.players["P1"].score, 22)
        teams = {row["id"]: row for row in e.mode_state["teams"]}
        self.assertEqual(teams["T1"]["score"], 22)
        self.assertEqual(teams["T2"]["alive"], 2)

    def test_team_elimination_has_team_winner(self):
        e = self.make()
        e.forfeit("P3")
        e.forfeit("P4")
        self.assertTrue(e.finished)
        payload = e.end_payload()
        self.assertEqual(payload["reason"], "last_standing")
        self.assertEqual(payload["winner"],
                         {"id": "T1", "name": "Team A", "kind": "team",
                          "members": ["P1", "P2"]})
        self.assertEqual(len(payload["team_standings"]), 2)

    def test_team_requires_exactly_four_players(self):
        for count in (2, 3):
            with self.subTest(count=count):
                players = [("Agent", "agent")] * count
                with self.assertRaisesRegex(
                        ValueError, "team mode requires exactly 4 players"):
                    Engine(Rules(), players, seed=2,
                           map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                           mode="team")

    def test_team_standings_use_hp_energy_and_id_tiebreakers(self):
        e = self.make()
        for player in e.players.values():
            player.score = 10
            player.energy = 20

        e.players["P2"].hp = 90
        self.assertEqual(e.end_payload(reason="turn_limit")
                         ["team_standings"][0]["id"], "T2")

        e.players["P2"].hp = 100
        e.players["P3"].energy = 30
        self.assertEqual(e.end_payload(reason="turn_limit")
                         ["team_standings"][0]["id"], "T2")

        e.players["P3"].energy = 20
        self.assertEqual(e.end_payload(reason="turn_limit")
                         ["team_standings"][0]["id"], "T1")


if __name__ == "__main__":
    unittest.main()
