import asyncio
import unittest

from arena_server.config import Rules
from arena_server.engine import ActionError, Engine, MapData, NODE_POINTS
from arena_server.logging_utils import NullLog
from arena_server.match import Match
from arena_server.participants import Participant


class RecordingServer:
    def __init__(self):
        self.messages = []
        self.spectator_messages = []
        self.config = type("Config", (), {"verbose": False})()

    async def send(self, participant, message):
        self.messages.append((participant, message))

    async def broadcast_spectators(self, message):
        self.spectator_messages.append(message)


class MatchDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def make_match(self, tick_ms=1000):
        participants = [
            Participant("A", "agent", "http", player_id="P1"),
            Participant("B", "agent", "http", player_id="P2"),
        ]
        engine = Engine(
            Rules(turn_limit=3), [("A", "agent"), ("B", "agent")],
            seed=3, match_id="deadline-test",
            map_data=MapData(15, 15, frozenset(), NODE_POINTS),
        )
        server = RecordingServer()
        ends = []

        async def on_end(ended):
            ends.append(ended)

        match = Match(
            engine, participants, server, tick_ms, 0, NullLog(), on_end,
        )
        return match, participants, server, ends

    async def test_submit_rejects_before_first_turn_opens(self):
        match, participants, _, _ = self.make_match()

        with self.assertRaises(ActionError) as ctx:
            match.submit(participants[0], match.engine.turn, {"type": "wait"})

        self.assertEqual(ctx.exception.code, "turn_closed")
        self.assertEqual(match.pending, {})

    async def test_submit_rejects_at_expired_active_deadline(self):
        match, participants, _, _ = self.make_match()
        loop = asyncio.get_running_loop()
        match.deadline = loop.time() - 0.001

        with self.assertRaises(ActionError) as ctx:
            match.submit(participants[0], match.engine.turn, {"type": "wait"})

        self.assertEqual(ctx.exception.code, "turn_closed")
        self.assertEqual(match.pending, {})

    async def test_finish_clears_active_deadline(self):
        match, _, _, ends = self.make_match()
        match.deadline = asyncio.get_running_loop().time() + 1

        await match._finish(match.engine.end_payload(reason="aborted"))

        self.assertIsNone(match.deadline)
        self.assertEqual(ends, [match])


if __name__ == "__main__":
    unittest.main()
