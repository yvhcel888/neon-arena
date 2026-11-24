import unittest
from arena_server.engine import SPAWN_POINTS, NODE_POINTS, generate_map, arena_connected


class TestMap(unittest.TestCase):
    def test_same_seed_same_map(self):
        self.assertEqual(generate_map(123).walls, generate_map(123).walls)

    def test_different_seeds_vary(self):
        signatures = {tuple(sorted(generate_map(s).walls)) for s in range(10)}
        self.assertGreater(len(signatures), 1)

    def test_rotational_symmetry(self):
        for seed in (1, 7, 42, 999):
            walls = generate_map(seed).walls
            self.assertEqual(
                {(14 - x, 14 - y) for x, y in walls},
                set(walls),
            )

    def test_spawns_and_nodes_clear_and_connected(self):
        for seed in range(1, 51):
            m = generate_map(seed)
            for pos in list(SPAWN_POINTS) + list(NODE_POINTS):
                self.assertNotIn(pos, m.walls)
            self.assertTrue(arena_connected(m), f"seed {seed} disconnected")

    def test_nodes_present(self):
        m = generate_map(5)
        self.assertEqual(tuple(m.nodes), NODE_POINTS)
