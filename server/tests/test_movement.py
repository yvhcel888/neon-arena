import unittest
from arena_server.config import Rules
from arena_server.engine import ActionError, Engine, MapData, NODE_POINTS


def open_engine(n=2):
    m = MapData(15, 15, frozenset(), NODE_POINTS)
    e = Engine(Rules(), [(f"Bot{i}", "agent") for i in range(1, n + 1)],
               seed=1, map_data=m)
    e.players["P1"].pos = (5, 5)
    if "P2" in e.players:
        e.players["P2"].pos = (9, 5)
    return e


class MovementTests(unittest.TestCase):
    def test_move_validates_direction_and_wall(self):
        e = open_engine()
        self.assertEqual(
            e.validate_action("P1", {"type": "move", "dir": "e"}, 1),
            {"type": "move", "dir": "e"},
        )
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "move", "dir": "x"}, 1)
        self.assertEqual(ctx.exception.code, "invalid_action")
        e.players["P1"].pos = (1, 5)
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "move", "dir": "w"}, 1)
        self.assertEqual(ctx.exception.code, "wall")

    def test_move_collision_and_occupied(self):
        e = open_engine()
        e.players["P2"].pos = (7, 5)
        e.resolve({
            "P1": {"type": "move", "dir": "e"},
            "P2": {"type": "move", "dir": "e"},
        })
        self.assertEqual(e.players["P1"].pos, (6, 5))
        self.assertEqual(e.players["P2"].pos, (8, 5))
        # 回到初始，制造同目标
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (7, 5)
        e.resolve({
            "P1": {"type": "move", "dir": "e"},   # (6,5)
            "P2": {"type": "move", "dir": "w"},   # (6,5)
        })
        self.assertEqual(e.players["P1"].pos, (5, 5))
        self.assertEqual(e.players["P2"].pos, (7, 5))
        # 目标格被不移动的玩家占用
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.resolve({"P1": {"type": "move", "dir": "e"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].pos, (5, 5))

    def test_dash_blocked_by_occupied_middle_and_cost_still_paid(self):
        e = open_engine()
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.players["P1"].energy = 50
        e.resolve({"P1": {"type": "dash", "dir": "e"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].pos, (5, 5))
        self.assertEqual(e.players["P1"].energy, 50 - 18 + 4)

    def test_energy_and_dead_validation(self):
        e = open_engine()
        e.players["P1"].energy = 0
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "attack", "dir": "e"}, 1)
        self.assertEqual(ctx.exception.code, "insufficient_energy")
        e.players["P1"].alive = False
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "wait"}, 1)
        self.assertEqual(ctx.exception.code, "not_alive")


if __name__ == "__main__":
    unittest.main()
