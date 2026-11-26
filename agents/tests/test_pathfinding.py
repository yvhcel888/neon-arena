import unittest

from arena_agent.pathfinding import (
    adjacent_dir, bfs_next_step, bfs_next_step_to_any,
)
from bots.heuristic import HeuristicPolicy
from bots.random_bot import RandomPolicy


RULES = {
    "max_hp": 100, "max_energy": 100,
    "attack": {"cost": 8},
    "dash": {"cost": 18, "distance": 2},
    "heal": {"cost": 25, "amount": 25},
    "shield": {"cost": 12, "amount": 26, "max": 40},
    "gather": {"energy": 30},
}


def start(mode="classic", state=None, walls=None, name="A"):
    return {
        "you": "P1", "mode": mode, "mode_state": state or {},
        "rules": RULES,
        "arena": {"width": 15, "height": 15, "walls": walls or []},
        "players": [{"id": "P1", "name": name, "pos": [1, 1]}],
    }


def player(pid, pos, **extra):
    return {
        "id": pid, "name": pid, "pos": pos, "hp": 100, "energy": 80,
        "shield": 0, "alive": True, **extra,
    }


def state(me=None, others=None, nodes=None, **extra):
    return {
        "turn": 1, "you": "P1",
        "players": [player("P1", me or [1, 1], team="T1",
                          bounty_target="P2", in_storm=True), *(others or [])],
        "nodes": nodes or [], "events": [], **extra,
    }


class PathTests(unittest.TestCase):
    def test_direct_and_blocked(self):
        self.assertEqual(bfs_next_step((1, 1), (1, 4), set(), set()), "s")
        enclosed = {(4, 5), (6, 5), (5, 4), (5, 6)}
        self.assertIsNone(bfs_next_step((1, 1), (5, 5), enclosed, set()))

    def test_no_path_returns_none(self):
        walls = {(0, 1), (1, 0), (2, 1), (1, 2)}
        self.assertIsNone(bfs_next_step((1, 1), (5, 5), walls, set()))

    def test_adjacent_direction(self):
        self.assertEqual(adjacent_dir((2, 2), (2, 1)), "n")
        self.assertIsNone(adjacent_dir((2, 2), (3, 3)))

    def test_occupied_and_out_of_bounds(self):
        self.assertIsNone(bfs_next_step((1, 1), (1, 2), set(), {(1, 2)}))
        self.assertIsNone(bfs_next_step((1, 1), (15, 1), set(), set()))

    def test_start_equals_goal_and_list_coordinates(self):
        self.assertIsNone(bfs_next_step([1, 1], (1, 1), set(), set()))
        self.assertEqual(
            bfs_next_step([1, 1], [3, 1], [[2, 0]], [[2, 1]]), "s",
        )

    def test_nearest_of_multiple_goals(self):
        self.assertEqual(
            bfs_next_step_to_any((1, 1), {(1, 3), (2, 1)}, set(), set()),
            "e",
        )
        self.assertIsNone(
            bfs_next_step_to_any((1, 1), {(1, 1)}, set(), set()),
        )


class ModeAwareHeuristicTests(unittest.TestCase):
    def test_survival_moves_toward_safe_zone(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(start("survival", {
            "zone": {"min": [6, 6], "max": [8, 8]},
        }))
        action = policy.decide(state([1, 1], []))
        self.assertIn(action["type"], {"move", "dash"})

    def test_survival_uses_current_zone_before_gathering(self):
        policy = HeuristicPolicy("collector")
        policy.on_start(start("survival", {
            "zone": {"min": [1, 1], "max": [13, 13]},
        }))
        snapshot = state([1, 1], [], nodes=[{
            "pos": [1, 1], "cooldown": 0, "active": True,
        }], mode="survival", mode_state={
            "zone": {"min": [6, 6], "max": [8, 8]},
        })
        self.assertEqual(policy.decide(snapshot),
                         {"type": "move", "dir": "e"})

    def test_team_does_not_target_friendly_player(self):
        policy = HeuristicPolicy("aggressive")
        policy.on_start(start("team", {"teams": []}))
        friendly = [player("P2", [2, 1], team="T1")]
        action = policy.decide(state([1, 1], friendly))
        self.assertNotEqual(action, {"type": "attack", "dir": "e"})

    def test_bounty_prefers_assigned_target(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(start("bounty", {
            "target_score": 150, "targets": {"P1": "P2"},
        }))
        others = [player("P2", [3, 1]), player("P3", [1, 3])]
        action = policy.decide(state([1, 1], others))
        self.assertEqual(action, {"type": "move", "dir": "e"})

    def test_bounty_attacks_adjacent_target_before_other_enemy(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(start("bounty", {"targets": {"P1": "P3"}}))
        snapshot = state([1, 1], [player("P2", [1, 2]),
                                  player("P3", [2, 1])])
        snapshot["players"][0]["bounty_target"] = "P3"
        self.assertEqual(policy.decide(snapshot),
                         {"type": "attack", "dir": "e"})

    def test_bounty_moves_toward_target_before_attacking_other_enemy(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(start("bounty", {"targets": {"P1": "P3"}}))
        snapshot = state([1, 1], [player("P2", [1, 2]),
                                  player("P3", [3, 1])])
        snapshot["players"][0]["bounty_target"] = "P3"
        self.assertEqual(policy.decide(snapshot),
                         {"type": "move", "dir": "e"})

    def test_king_moves_toward_center_zone(self):
        policy = HeuristicPolicy("collector")
        policy.on_start(start("king", {
            "zone": {"min": [6, 6], "max": [8, 8]}, "target_score": 100,
        }))
        action = policy.decide(state([1, 1], [], nodes=[{
            "pos": [1, 2], "cooldown": 0, "active": True,
        }]))
        self.assertEqual(action, {"type": "move", "dir": "e"})

    def test_strategy_changes_healing_threshold(self):
        aggressive = HeuristicPolicy("aggressive")
        balanced = HeuristicPolicy("balanced")
        for policy in (aggressive, balanced):
            policy.on_start(start())
        hurt = state([1, 1], [player("P2", [2, 1])])
        hurt["players"][0]["hp"] = 50
        self.assertEqual(aggressive.decide(hurt), {"type": "heal"})
        self.assertEqual(balanced.decide(hurt), {"type": "attack", "dir": "e"})

    def test_collector_gathers_and_respects_cooldown(self):
        policy = HeuristicPolicy("collector")
        policy.on_start(start())
        active = state(nodes=[{"pos": [1, 1], "cooldown": 0, "active": True}])
        self.assertEqual(policy.decide(active), {"type": "gather"})
        active["nodes"][0].update(cooldown=2, active=False)
        self.assertNotEqual(policy.decide(active), {"type": "gather"})

    def test_movement_avoids_walls_occupants_and_low_energy(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(start(walls=[[2, 1]]))
        snapshot = state([1, 1], [player("P2", [1, 2])])
        snapshot["players"][0]["energy"] = 0
        action = policy.decide(snapshot)
        self.assertEqual(action, {"type": "wait"})

    def test_bounty_falls_back_when_assigned_target_is_dead(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(start("bounty", {"targets": {"P1": "P2"}}))
        others = [player("P2", [3, 1], alive=False), player("P3", [1, 3])]
        self.assertEqual(policy.decide(state([1, 1], others)),
                         {"type": "move", "dir": "s"})


class RandomPolicyTests(unittest.TestCase):
    def test_same_name_is_deterministic_and_actions_are_legal(self):
        first = RandomPolicy("Alpha")
        second = RandomPolicy("Alpha")
        payload = start(name="Alpha")
        first.on_start(payload)
        second.on_start(payload)
        snapshot = state([1, 1], [player("P2", [3, 1])], nodes=[{
            "pos": [1, 1], "cooldown": 0, "active": True,
        }])
        # Independently enumerated from the rules: east/south moves and a
        # south dash remain walkable; east dash lands on P2. P1 can attack in
        # any direction, gather, or shield, but cannot heal at full HP.
        expected_legal = {
            ("wait", None),
            ("move", "e"), ("move", "s"),
            ("dash", "s"),
            ("attack", "n"), ("attack", "e"),
            ("attack", "s"), ("attack", "w"),
            ("gather", None), ("shield", None),
        }
        for turn in range(40):
            action = first.decide(snapshot)
            with self.subTest(turn=turn):
                self.assertEqual(action, second.decide(snapshot))
                self.assertIn((action.get("type"), action.get("dir")),
                              expected_legal)

    def test_multiple_seeds_never_move_or_dash_through_border(self):
        snapshot = state([1, 1])
        # Names are deterministic RandomPolicy RNG seeds. From [1, 1], only
        # east and south stay inside the 15x15 arena's impassable border.
        for name in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"):
            policy = RandomPolicy(name)
            policy.on_start(start(name=name))
            movement_types = set()
            for turn in range(100):
                action = policy.decide(snapshot)
                with self.subTest(seed=name, turn=turn, action=action):
                    if action.get("type") in {"move", "dash"}:
                        movement_types.add(action["type"])
                        self.assertIn(
                            action.get("dir"), {"e", "s"},
                            "north/west move or dash from [1,1] crosses "
                            "the impassable border",
                        )
            self.assertEqual(movement_types, {"move", "dash"}, name)

    def test_actions_match_independent_legal_set_with_obstacles_and_low_energy(self):
        policy = RandomPolicy("Alpha")
        policy.on_start(start(name="Alpha", walls=[[2, 1]]))
        snapshot = state(
            [1, 1], [player("P2", [1, 2])],
            nodes=[{"pos": [1, 1], "cooldown": 3, "active": False}],
        )
        snapshot["players"][0]["energy"] = 12

        # Independent oracle for this exact snapshot:
        # - border blocks north/west, a wall blocks east, and P2 blocks south;
        # - 12 energy permits attack (8) and shield (12), but not dash (18)
        #   or heal (25);
        # - the cooling node cannot be gathered.
        expected_legal = {
            ("wait", None),
            ("attack", "n"), ("attack", "e"),
            ("attack", "s"), ("attack", "w"),
            ("shield", None),
        }
        observed = set()
        for turn in range(100):
            action = policy.decide(snapshot)
            with self.subTest(turn=turn, action=action):
                key = (action.get("type"), action.get("dir"))
                observed.add(key)
                self.assertIn(key, expected_legal)
        self.assertEqual(observed, expected_legal)

    def test_does_not_gather_cooling_node_or_dash_without_energy(self):
        policy = RandomPolicy("Alpha")
        policy.on_start(start())
        snapshot = state(nodes=[{"pos": [1, 1], "cooldown": 3, "active": False}])
        snapshot["players"][0]["energy"] = 0
        for _ in range(100):
            action = policy.decide(snapshot)
            self.assertNotEqual(action["type"], "gather")
            self.assertNotEqual(action["type"], "dash")


if __name__ == "__main__":
    unittest.main()
