import asyncio
from contextlib import redirect_stderr
import io
import unittest

from arena_server.config import Rules, ServerConfig
from arena_server.engine import ActionError, Engine, MapData, NODE_POINTS
from arena_server.logging_utils import NullLog
from arena_server.match import Match
from arena_server.participants import Participant
from arena_server.server import GameServer


class AlwaysFailCloseLog:
    def write(self, payload):
        pass

    def close(self):
        raise OSError("persistent close failure")


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


class MatchShutdownTests(unittest.IsolatedAsyncioTestCase):
    def make_match(self, log=None, server=None, on_end=None):
        participants = [
            Participant("A", "agent", "http", player_id="P1"),
            Participant("B", "agent", "http", player_id="P2"),
        ]
        engine = Engine(
            Rules(turn_limit=3), [("A", "agent"), ("B", "agent")],
            seed=3, match_id="shutdown-test",
            map_data=MapData(15, 15, frozenset(), NODE_POINTS),
        )
        match = Match(
            engine, participants, server or RecordingServer(), 1000, 0,
            log or NullLog(), on_end,
        )
        return match, participants

    async def test_server_stop_clears_match_when_log_close_always_fails(self):
        server = GameServer(ServerConfig(no_logs=True))
        match, participants = self.make_match(
            log=AlwaysFailCloseLog(), server=server,
        )
        for participant in participants:
            participant.state = "playing"
            participant.match = match
        server.match = match
        diagnostics = io.StringIO()

        with redirect_stderr(diagnostics):
            await server.stop()

        self.assertIn("persistent close failure", diagnostics.getvalue())
        self.assertIsNone(server.match)
        for participant in participants:
            self.assertEqual(participant.state, "idle")
            self.assertIsNone(participant.match)

    async def test_match_cancellation_preserves_cancelled_error_when_log_close_fails(self):
        entered = asyncio.Event()

        async def wait_forever():
            entered.set()
            await asyncio.Event().wait()

        match, _ = self.make_match(log=AlwaysFailCloseLog())
        original_run = match.run
        match.run = wait_forever
        task = asyncio.create_task(match.run())
        await entered.wait()
        match.run = original_run
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_match_cancel_handler_survives_log_close_failure(self):
        log = AlwaysFailCloseLog()

        async def broadcast_spectators(message):
            raise asyncio.CancelledError

        match, _ = self.make_match(log=log)
        match.closed = False
        match.server.broadcast_spectators = broadcast_spectators
        diagnostics = io.StringIO()

        with redirect_stderr(diagnostics):
            with self.assertRaises(asyncio.CancelledError):
                await match.run()

        self.assertTrue(match.closed)
        self.assertIn("persistent close failure", diagnostics.getvalue())


if __name__ == "__main__":
    unittest.main()
