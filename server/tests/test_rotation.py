import unittest

from arena_server.modes import select_mode


class ModeFrameworkTests(unittest.TestCase):
    def test_rotation_skips_team_when_only_two_players(self):
        self.assertEqual(select_mode("rotation", 2, 2), ("survival", 4))
        self.assertEqual(select_mode("rotation", 4, 2), ("team", 3))
        self.assertEqual(select_mode("king", 2, 4), ("king", 4))

    def test_skipped_team_mode_is_not_immediately_revisited(self):
        _, cursor = select_mode("rotation", 2, 2)
        self.assertEqual(select_mode("rotation", 2, cursor), ("bounty", 0))


if __name__ == "__main__":
    unittest.main()
