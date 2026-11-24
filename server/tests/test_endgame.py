import unittest
from arena_server.config import Rules
from arena_server.engine import ActionError, Engine, MapData, NODE_POINTS

class EndgameTests(unittest.TestCase):
    def make(self, limit=2):
        e = Engine(Rules(turn_limit=limit), [("A", "agent"), ("B", "agent")],
                   seed=3, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (9, 9)
        return e

    def test_turn_limit_winner(self):
        e = self.make(1)
        e.players["P1"].score = 5
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_payload()["reason"], "turn_limit")
        self.assertEqual(e.end_payload()["winner"]["id"], "P1")

    def test_mutual_destruction(self):
        e = self.make(5)
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.players["P1"].hp = e.players["P2"].hp = 5
        e.players["P1"].energy = e.players["P2"].energy = 50
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "attack", "dir": "w"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_payload()["reason"], "mutual_destruction")
        self.assertIsNotNone(e.end_payload()["winner"])

    def test_forfeit(self):
        e = self.make(5)
        e.forfeit("P2")
        self.assertTrue(e.finished)
        self.assertEqual(e.players["P1"].alive, True)
        self.assertEqual(e.end_payload()["reason"], "last_standing")

    def test_four_consecutive_missed_submissions_forfeit(self):
        e = self.make(10)
        for turn in range(1, 4):
            e.resolve({"P1": {"type": "wait"}})
            self.assertTrue(e.players["P2"].alive)
            self.assertEqual(e.players["P2"].missed_turns, turn)
        e.resolve({"P1": {"type": "wait"}})
        self.assertFalse(e.players["P2"].alive)
        self.assertEqual(e.players["P2"].hp, 0)
        self.assertTrue(e.players["P2"].forfeited)
        self.assertEqual(e.players["P2"].missed_turns, 4)
        self.assertIn({"type": "forfeit", "player": "P2"}, e.last_events)
        self.assertNotIn({"type": "death", "player": "P2", "killer": None},
                         e.last_events)
        self.assertEqual(e.end_reason, "last_standing")

    def test_submission_resets_missed_turns_and_dead_player_does_not_miss(self):
        e = self.make(10)
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        e.resolve({"P1": {"type": "wait"}})
        self.assertEqual(e.players["P2"].missed_turns, 1)
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P2"].missed_turns, 0)
        e.forfeit("P2")
        e.resolve({"P1": {"type": "wait"}})
        self.assertEqual(e.players["P2"].missed_turns, 0)
        self.assertEqual(e.completed_turns, 3)

    def test_standings_sort_alive_score_hp_energy_then_id(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent"),
                             ("C", "agent"), ("D", "agent")],
                   seed=3, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.players["P1"].alive = False
        e.players["P2"].score = 20
        e.players["P3"].score = 20
        e.players["P4"].score = 20
        e.players["P2"].hp = 80
        e.players["P3"].hp = 90
        e.players["P4"].hp = 90
        e.players["P2"].energy = 90
        e.players["P3"].energy = 30
        e.players["P4"].energy = 30
        self.assertEqual([row["id"] for row in e.standings()],
                         ["P3", "P4", "P2", "P1"])

    def test_last_finished_turn_does_not_increment_and_resolve_is_terminal(self):
        e = self.make(1)
        events = e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.turn, 1)
        self.assertEqual(e.completed_turns, 1)
        payload = e.end_payload()
        self.assertEqual(payload["turns"], 1)
        self.assertEqual(payload["events_turn"], 1)
        self.assertEqual(payload["events"], events)
        self.assertEqual(e.resolve({"P1": {"type": "wait"}}), [])
        self.assertEqual(e.completed_turns, 1)

    def test_last_standing_precedes_turn_limit(self):
        e = self.make(1)
        e.players["P2"].alive = False
        e.players["P2"].hp = 0
        e.resolve({"P1": {"type": "wait"}})
        self.assertEqual(e.end_reason, "last_standing")
        self.assertEqual(e.end_payload()["winner"]["id"], "P1")

    def test_aborted_payload_has_no_winner_and_complete_standings(self):
        e = self.make(5)
        self.assertIsNone(e.end_payload("aborted")["winner"])
        payload = e.end_payload("aborted")
        self.assertEqual(payload["match_id"], "local")
        self.assertEqual(payload["reason"], "aborted")
        self.assertEqual(len(payload["standings"]), 2)
        self.assertEqual(payload["turns"], 0)


class EngineReviewRegressionTests(unittest.TestCase):
    def make(self, limit=10):
        e = Engine(Rules(turn_limit=limit),
                   [("A", "agent"), ("B", "agent")],
                   seed=3, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (9, 9)
        return e

    def test_forfeit_after_resolved_turn_does_not_mix_events(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent"),
                             ("C", "agent")],
                   seed=4, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.players["P1"].energy = 100
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"}})
        self.assertTrue(e.last_events)
        self.assertTrue(e.forfeit("P3"))
        self.assertFalse(e.finished)
        self.assertEqual(e.last_events,
                         [{"type": "forfeit", "player": "P3"}])
        self.assertEqual(e.events_turn, 2)

    def test_invalid_action_does_not_reset_missed_turns(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")],
                   seed=4, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.resolve({"P1": {"type": "wait"}})
        self.assertEqual(e.players["P2"].missed_turns, 1)
        e.resolve({"P1": {"type": "wait"},
                   "P2": {"type": "not-an-action"}})
        self.assertEqual(e.players["P2"].missed_turns, 2)

    def test_malformed_direction_is_treated_as_missed_turn(self):
        for action_type in ("move", "dash", "attack"):
            for direction in ([], {}, None):
                with self.subTest(action_type=action_type, direction=direction):
                    e = self.make(10)
                    e.resolve({"P1": {"type": "wait"}})
                    self.assertEqual(e.players["P2"].missed_turns, 1)
                    player = e.players["P2"]
                    start_pos = player.pos
                    start_energy = player.energy

                    events = e.resolve({
                        "P1": {"type": "wait"},
                        "P2": {"type": action_type, "dir": direction},
                    })

                    self.assertEqual(player.missed_turns, 2)
                    self.assertEqual(player.pos, start_pos)
                    self.assertEqual(player.energy,
                                     start_energy + e.rules.energy_regen)
                    self.assertFalse(any(event.get("player") == "P2"
                                         for event in events))

    def test_validate_action_rejects_malformed_direction(self):
        e = self.make(10)
        for action_type in ("move", "dash", "attack"):
            for direction in ([], {}, None):
                with self.subTest(action_type=action_type, direction=direction):
                    with self.assertRaises(ActionError) as ctx:
                        e.validate_action("P1",
                                          {"type": action_type, "dir": direction},
                                          e.turn)
                    self.assertEqual(ctx.exception.code, "invalid_action")

    def test_under_resourced_attack_after_missed_turn_is_wait(self):
        e = self.make(10)
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.resolve({"P1": {"type": "wait"}})
        self.assertEqual(e.players["P2"].missed_turns, 1)
        player = e.players["P2"]
        player.energy = e.rules.attack_cost - 1
        start_energy = player.energy
        attacker_hp = e.players["P1"].hp

        events = e.resolve({
            "P1": {"type": "wait"},
            "P2": {"type": "attack", "dir": "w"},
        })

        self.assertEqual(player.missed_turns, 2)
        self.assertEqual(player.energy, start_energy + e.rules.energy_regen)
        self.assertFalse(any(event.get("player") == "P2"
                             for event in events))
        self.assertFalse(any(event["type"] == "damage" for event in events))
        self.assertEqual(e.players["P1"].hp, attacker_hp)


if __name__ == "__main__":
    unittest.main()
