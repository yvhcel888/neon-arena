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


class RotationSelectionTests(unittest.TestCase):
    def test_two_players_skip_team(self):
        self.assertEqual(select_mode("rotation", 2, 0), ("classic", 1))
        self.assertEqual(select_mode("rotation", 2, 1), ("king", 2))
        # The cursor is the next mode index: survival is 3, bounty is 4.
        self.assertEqual(select_mode("rotation", 2, 2), ("survival", 4))

    def test_four_players_allow_team(self):
        self.assertEqual(select_mode("rotation", 4, 2), ("team", 3))

    def test_fixed_mode_does_not_advance(self):
        self.assertEqual(select_mode("bounty", 2, 4), ("bounty", 4))


if __name__ == "__main__":
    unittest.main()
