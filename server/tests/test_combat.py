import unittest
from arena_server.config import Rules
from arena_server.engine import ActionError, Engine, MapData, NODE_POINTS


def engine():
    e = Engine(Rules(), [("A", "agent"), ("B", "agent")],
               seed=2, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
    e.players["P1"].pos = (5, 5)
    e.players["P2"].pos = (6, 5)
    e.players["P1"].energy = 50
    e.players["P2"].energy = 50
    return e

class CombatTests(unittest.TestCase):
    def test_attack_uses_post_movement_position_and_shield(self):
        e = engine()
        e.players["P2"].shield = 20
        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "shield"},
        })
        self.assertEqual(e.players["P1"].energy, 50 - 8 + 4)
        self.assertEqual(e.players["P2"].energy, 50 - 12 + 4)
        # 攻击在 shield 动作生效后结算：40 吸收 22，剩余 18 护盾，HP 不变
        self.assertEqual(e.players["P2"].shield, 18)
        self.assertEqual(e.players["P2"].hp, 100)

    def test_move_out_of_range_dodges(self):
        e = engine()
        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "move", "dir": "e"},
        })
        self.assertEqual(e.players["P2"].hp, 100)
        self.assertEqual(e.players["P1"].energy, 50 - 8 + 4)

    def test_simultaneous_kill_credit(self):
        e = engine()
        e.players["P1"].hp = 10
        e.players["P2"].hp = 10
        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "attack", "dir": "w"},
        })
        self.assertFalse(e.players["P1"].alive)
        self.assertFalse(e.players["P2"].alive)
        self.assertEqual(e.players["P1"].kills, 1)
        self.assertEqual(e.players["P2"].kills, 1)

    def test_gather_and_node_cooldown(self):
        e = engine()
        e.players["P1"].pos = (7, 7)
        e.players["P1"].energy = 50
        e.resolve({"P1": {"type": "gather"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].energy, 80 + 4)  # 50 + 30 + regen
        self.assertEqual(e.players["P1"].score, 10)
        node = next(n for n in e.nodes if n.pos == (7, 7))
        self.assertEqual(node.cooldown, 3)  # 4 设置后本回合 -1

class ResourceAndCombatBoundaryTests(unittest.TestCase):
    def test_resource_validation_uses_distinct_error_codes(self):
        e = engine()
        cases = (
            ("gather", {}, "no_active_node"),
            ("shield", {}, "shield_full"),
            ("heal", {}, "full_hp"),
        )
        e.players["P1"].shield = Rules().max_shield
        for action_type, params, code in cases:
            with self.subTest(action=action_type):
                with self.assertRaises(ActionError) as ctx:
                    e.validate_action("P1", {"type": action_type, **params}, 1)
                self.assertEqual(ctx.exception.code, code)
        e.players["P1"].pos = (7, 7)
        e.players["P1"].shield = 0
        e.players["P1"].hp = 50
        self.assertEqual(e.validate_action("P1", {"type": "gather"}, 1),
                         {"type": "gather"})
        node = next(n for n in e.nodes if n.pos == (7, 7))
        node.cooldown = 1
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "gather"}, 1)
        self.assertEqual(ctx.exception.code, "no_active_node")

    def test_shield_overflow_absorbs_before_hp_without_damage_score(self):
        e = engine()
        e.players["P1"].energy = 100
        e.players["P2"].shield = 20
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "shield"}})
        self.assertEqual(e.players["P2"].shield, 18)
        self.assertEqual(e.players["P2"].hp, 100)
        self.assertEqual(e.players["P1"].score, 0)
        e.players["P2"].shield = 5
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}})
        self.assertEqual(e.players["P2"].shield, 0)
        self.assertEqual(e.players["P2"].hp, 83)
        self.assertEqual(e.players["P1"].score, 17)
        self.assertEqual(e.players["P1"].damage_dealt, 17)
        damage_events = [event for event in e.last_events if event["type"] == "damage"]
        self.assertEqual(damage_events[-1], {
            "type": "damage", "player": "P1", "target": "P2",
            "hp_damage": 17, "shield_damage": 5,
        })

    def test_heal_shield_and_energy_caps(self):
        e = engine()
        e.players["P1"].hp = 90
        e.players["P2"].shield = 20
        e.players["P2"].energy = 95
        e.resolve({"P1": {"type": "heal"}, "P2": {"type": "shield"}})
        self.assertEqual(e.players["P1"].hp, 100)
        self.assertEqual(e.players["P1"].energy, 29)
        self.assertEqual(e.players["P2"].shield, 40)
        self.assertEqual(e.players["P2"].energy, 87)
        self.assertIn({"type": "heal", "player": "P1", "amount": 10,
                       "hp": 100}, e.last_events)
        self.assertIn({"type": "shield", "player": "P2", "amount": 20,
                       "shield": 40}, e.last_events)
        e.players["P1"].energy = 90
        e.players["P1"].pos = (7, 7)
        e.resolve({"P1": {"type": "gather"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].energy, 100)
        self.assertEqual(e.players["P1"].score, 10)

    def test_attack_miss_still_costs_energy_and_emits_event(self):
        e = engine()
        e.players["P1"].pos = (5, 5)
        e.players["P2"].pos = (8, 8)
        e.resolve({"P1": {"type": "attack", "dir": "n"},
                   "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].energy, 46)
        self.assertEqual(e.players["P1"].score, 0)
        self.assertIn({"type": "attack", "player": "P1", "dir": "n",
                       "target": None}, e.last_events)

    def test_kill_damage_tie_goes_to_lowest_player_id(self):
        e = Engine(Rules(attack_damage=1), [("C", "agent"), ("A", "agent"),
                                           ("B", "agent")],
                   seed=2, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        for player_id in ("P1", "P2", "P3"):
            e.players[player_id].energy = 50
        e.players["P1"].pos = (5, 4)
        e.players["P2"].pos = (5, 6)
        e.players["P3"].pos = (5, 5)
        e.players["P3"].hp = 1
        e.resolve({"P1": {"type": "attack", "dir": "s"},
                   "P2": {"type": "attack", "dir": "n"},
                   "P3": {"type": "wait"}})
        self.assertFalse(e.players["P3"].alive)
        self.assertEqual(e.players["P1"].kills, 1)
        self.assertEqual(e.players["P2"].kills, 0)
        self.assertEqual(e.players["P1"].score, 26)
        self.assertIn({"type": "death", "player": "P3", "killer": "P1"},
                      e.last_events)

    def test_heal_and_gather_event_fields(self):
        e = engine()
        e.players["P1"].hp = 50
        e.players["P1"].pos = (7, 7)
        e.resolve({"P1": {"type": "heal"}, "P2": {"type": "wait"}})
        self.assertIn({"type": "heal", "player": "P1", "amount": 25,
                       "hp": 75}, e.last_events)
        e.players["P1"].pos = (7, 7)
        e.resolve({"P1": {"type": "gather"}, "P2": {"type": "wait"}})
        self.assertIn({"type": "gather", "player": "P1", "pos": [7, 7],
                       "energy_gain": 30, "score_gain": 10}, e.last_events)


if __name__ == "__main__":
    unittest.main()
