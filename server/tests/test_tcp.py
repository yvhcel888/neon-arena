import asyncio
from contextlib import redirect_stderr
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_server.config import ServerConfig
from arena_server.server import GameServer


class TcpHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = self.make_server()
        self.tcp_port, self.api_port = await self.server.start()
        self.assertIsInstance(self.api_port, int)
        self.assertGreater(self.api_port, 0)
        self.writers = []

    def make_server(self, **overrides):
        values = {
            "host": "127.0.0.1", "tcp_port": 0, "api_port": 0,
            "tick_ms": 500, "min_turn_ms": 0, "turn_limit": 3,
            "lobby_wait_ms": 20, "seed": 11, "no_logs": True,
        }
        values.update(overrides)
        return GameServer(ServerConfig(**values))

    async def restart(self, **overrides):
        await self.server.stop()
        self.server = self.make_server(**overrides)
        self.tcp_port, self.api_port = await self.server.start()
        self.assertIsInstance(self.api_port, int)
        self.assertGreater(self.api_port, 0)

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        await self.server.stop()

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)
        self.writers.append(writer)
        welcome = await self.read_json(reader)
        self.assertEqual(welcome["type"], "welcome")
        self.assertEqual(welcome["protocol"], 1)
        self.assertTrue(welcome["client_id"])
        return reader, writer

    async def send(self, writer, msg):
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()

    async def read_json(self, reader, timeout=5):
        line = await asyncio.wait_for(reader.readline(), timeout)
        self.assertTrue(line, "connection closed")
        return json.loads(line)

    async def read_until(self, reader, wanted, timeout=5):
        wanted = {wanted} if isinstance(wanted, str) else set(wanted)
        while True:
            msg = await self.read_json(reader, timeout)
            if msg["type"] in wanted:
                return msg

    async def join(self, reader, writer, name):
        await self.send(writer, {"type": "join", "protocol": 1, "name": name})
        return await self.read_until(reader, "start")

    async def play_waits(self, reader, writer):
        last_turn = -1
        while True:
            msg = await self.read_json(reader)
            if msg["type"] == "state" and msg["turn"] != last_turn:
                last_turn = msg["turn"]
                me = next(p for p in msg["players"] if p["id"] == msg["you"])
                if me["alive"]:
                    await self.send(writer, {
                        "type": "action", "turn": msg["turn"],
                        "action": {"type": "wait"},
                    })
            if msg["type"] == "end":
                return msg

    async def test_two_agents_lobby_match_and_end(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        lobbies = []

        async def collect(reader, writer, name):
            await self.send(writer, {"type": "join", "protocol": 1, "name": name})
            while True:
                msg = await self.read_json(reader)
                if msg["type"] == "lobby":
                    lobbies.append(msg)
                if msg["type"] == "start":
                    return msg

        start1, start2 = await asyncio.gather(
            collect(r1, w1, "A"), collect(r2, w2, "B"),
        )
        self.assertEqual(start1["you"], "P1")
        self.assertEqual(start2["you"], "P2")
        self.assertEqual(start1["players"][0]["kind"], "agent")
        self.assertEqual(start1["mode"], "classic")
        self.assertIn("mode_state", start1)
        self.assertTrue(lobbies, "no lobby broadcast observed")
        self.assertEqual({p["name"] for p in lobbies[-1]["players"]}, {"A", "B"})
        self.assertEqual(lobbies[-1]["mode"], "classic")
        self.assertIn("mode_label", lobbies[-1])
        self.assertIn("mode_description", lobbies[-1])

        end1, end2 = await asyncio.gather(
            self.play_waits(r1, w1), self.play_waits(r2, w2),
        )
        self.assertEqual(end1["reason"], "turn_limit")
        self.assertEqual(end1["match_id"], end2["match_id"])
        self.assertEqual(len(end1["standings"]), 2)

    async def test_spectator_gets_start_and_state_snapshot(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        await asyncio.gather(
            self.join(r1, w1, "A"), self.join(r2, w2, "B"),
        )
        rs, ws = await self.connect()
        await self.send(ws, {"type": "spectate"})
        msg = await self.read_until(rs, "spectating")
        self.assertTrue(msg["match_running"])
        start = await self.read_until(rs, "start")
        self.assertNotIn("you", start)
        state = await self.read_until(rs, "state")
        self.assertNotIn("you", state)
        self.assertEqual(state["mode"], "classic")
        self.assertIn("mode_state", state)
        self.assertGreaterEqual(state["turn"], 1)

    async def test_disconnect_forfeits_and_ends_match(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        await asyncio.gather(
            self.join(r1, w1, "A"), self.join(r2, w2, "B"),
        )
        await self.read_until(r1, "state")
        w2.close()
        state = await self.read_until(r1, "state", timeout=5)
        self.assertEqual(state["turn"], 1)
        self.assertEqual(state["events_turn"], 1)
        self.assertEqual(state["events"],
                         [{"type": "forfeit", "player": "P2"}])
        end = await self.read_until(r1, "end", timeout=5)
        self.assertEqual(end["reason"], "last_standing")
        self.assertEqual(end["winner"]["id"], "P1")

    async def test_third_player_leave_broadcasts_forfeit_and_match_continues(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as log_dir:
            await self.restart(tick_ms=30000, min_turn_ms=0, turn_limit=3,
                               lobby_wait_ms=20, no_logs=False,
                               log_dir=log_dir)
            r1, w1 = await self.connect()
            r2, w2 = await self.connect()
            r3, w3 = await self.connect()
            await asyncio.gather(
                self.join(r1, w1, "A"), self.join(r2, w2, "B"),
                self.join(r3, w3, "C"),
            )
            match = self.server.match
            initial = await asyncio.gather(
                self.read_until(r1, "state"), self.read_until(r2, "state"),
                self.read_until(r3, "state"),
            )
            self.assertEqual([state["turn"] for state in initial], [1, 1, 1])

            rs, ws = await self.connect()
            await self.send(ws, {"type": "spectate"})
            await self.read_until(rs, "spectating")
            spectator_start = await self.read_until(rs, "start")
            self.assertNotIn("you", spectator_start)
            spectator_initial = await self.read_until(rs, "state")
            self.assertNotIn("you", spectator_initial)

            await asyncio.gather(*(
                self.send(writer, {
                    "type": "action", "turn": 1,
                    "action": {"type": "wait"},
                })
                for writer in (w1, w2, w3)
            ))
            await asyncio.gather(*(
                self.read_until(reader, "action_ack")
                for reader in (r1, r2, r3)
            ))
            resolved = await asyncio.gather(
                self.read_until(r1, "state"), self.read_until(r2, "state"),
                self.read_until(r3, "state"), self.read_until(rs, "state"),
            )
            self.assertEqual([state["turn"] for state in resolved],
                             [2, 2, 2, 2])
            self.assertTrue(all(not any(event["type"] == "forfeit"
                                        for event in state["events"])
                                for state in resolved))

            await self.send(w3, {"type": "leave"})
            leaver_messages = []
            while True:
                message = await self.read_json(r3)
                leaver_messages.append(message)
                if message["type"] == "left":
                    break
            self.assertFalse(any(message["type"] in ("state", "end")
                                 for message in leaver_messages),
                             "leaver received its own forfeit delivery")

            forfeit_states = await asyncio.gather(
                self.read_until(r1, "state"), self.read_until(r2, "state"),
                self.read_until(rs, "state"),
            )
            self.assertIs(self.server.match, match)
            self.assertFalse(match.engine.finished)
            self.assertEqual(match.engine.completed_turns, 1)
            for state, player_id in zip(forfeit_states, ("P1", "P2", None)):
                self.assertEqual(state["type"], "state")
                self.assertEqual(state["turn"], 2)
                self.assertEqual(state["events_turn"], 2)
                self.assertEqual(state["events"],
                                 [{"type": "forfeit", "player": "P3"}])
                if player_id is None:
                    self.assertNotIn("you", state)
                else:
                    self.assertEqual(state["you"], player_id)
                leaver = next(player for player in state["players"]
                              if player["id"] == "P3")
                self.assertFalse(leaver["alive"])
                self.assertTrue(leaver["stats"]["forfeited"])

            await asyncio.gather(*(
                self.send(writer, {
                    "type": "action", "turn": 2,
                    "action": {"type": "wait"},
                })
                for writer in (w1, w2)
            ))
            await asyncio.gather(
                self.read_until(r1, "action_ack"),
                self.read_until(r2, "action_ack"),
            )
            post_forfeit = await asyncio.gather(
                self.read_until(r1, "state"), self.read_until(r2, "state"),
                self.read_until(rs, "state"),
            )
            for state in post_forfeit:
                self.assertEqual(state["turn"], 3)
                self.assertEqual(state["events_turn"], 2)
                self.assertFalse(any(event["type"] == "forfeit"
                                     for event in state["events"]))

            await asyncio.gather(*(
                self.send(writer, {
                    "type": "action", "turn": 3,
                    "action": {"type": "wait"},
                })
                for writer in (w1, w2)
            ))
            ends = await asyncio.gather(
                self.read_until(r1, "end"), self.read_until(r2, "end"),
                self.read_until(rs, "end"),
            )
            self.assertEqual([end["reason"] for end in ends],
                             ["turn_limit"] * 3)
            await asyncio.wait_for(self.server._match_task, 1)
            await self.send(w3, {"type": "ping", "ts": "drained"})
            drained = []
            while True:
                message = await self.read_json(r3)
                drained.append(message)
                if message["type"] == "pong":
                    self.assertEqual(message["ts"], "drained")
                    break
            self.assertFalse(any(message["type"] in ("state", "end")
                                 for message in drained),
                             "leaver received stale post-forfeit delivery")

            files = list(Path(log_dir).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            records = [json.loads(line) for line in
                       files[0].read_text(encoding="utf-8").splitlines()]
            forfeit_records = [
                record for record in records
                if record["type"] == "state"
                and record["events"] == [
                    {"type": "forfeit", "player": "P3"},
                ]
            ]
            self.assertEqual(len(forfeit_records), 1)
            self.assertEqual(forfeit_records[0]["turn"], 2)
            self.assertEqual(forfeit_records[0]["events_turn"], 2)
            self.assertNotIn("you", forfeit_records[0])
            self.assertEqual([record["type"] for record in records],
                             ["start", "state", "state", "state", "state",
                              "end"])

    async def test_rejoined_player_does_not_receive_old_match_delivery(self):
        await self.restart(tick_ms=1000, min_turn_ms=0, turn_limit=2,
                           lobby_wait_ms=20)
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        r3, w3 = await self.connect()
        starts = await asyncio.gather(
            self.join(r1, w1, "A"), self.join(r2, w2, "B"),
            self.join(r3, w3, "C"),
        )
        old_match = self.server.match
        old_participant = next(
            participant for participant in old_match.participants
            if participant.name == "C"
        )
        old_match_id = starts[0]["match_id"]
        states = await asyncio.gather(
            self.read_until(r1, "state"), self.read_until(r2, "state"),
            self.read_until(r3, "state"),
        )
        self.assertEqual(states[2]["you"], "P3")

        await self.send(w3, {"type": "leave"})
        await self.read_until(r3, "left")
        await self.send(w3, {"type": "join", "protocol": 1,
                             "name": "C-new"})
        await self.read_until(r3, "joined")
        self.assertEqual(len(self.server.lobby.waiting), 1)
        rejoined = self.server.lobby.waiting[0]
        self.assertIsNot(rejoined, old_participant)

        for reader, writer in ((r1, w1), (r2, w2)):
            await self.send(writer, {
                "type": "action", "turn": 1, "action": {"type": "wait"},
            })
            await self.read_until(reader, "action_ack")
        next_states = await asyncio.gather(
            self.read_until(r1, "state"), self.read_until(r2, "state"),
        )
        self.assertEqual([state["turn"] for state in next_states], [2, 2])
        for reader, writer in ((r1, w1), (r2, w2)):
            await self.send(writer, {
                "type": "action", "turn": 2, "action": {"type": "wait"},
            })
        ends = await asyncio.gather(
            self.read_until(r1, "end"), self.read_until(r2, "end"),
        )
        self.assertEqual([end["match_id"] for end in ends],
                         [old_match_id, old_match_id])

        # The old end was queued before P1/P2 observed it. A subsequent pong
        # establishes an ordering barrier so stale delivery cannot arrive later.
        await self.send(w3, {"type": "ping", "ts": "drained"})
        messages = []
        while True:
            message = await self.read_json(r3)
            messages.append(message)
            if message["type"] == "pong":
                self.assertEqual(message["ts"], "drained")
                break
        stale = [message for message in messages
                 if message["type"] in ("state", "end")]
        self.assertEqual(stale, [], "rejoined connection received old match data")

    async def test_fixed_king_mode_reaches_start_and_state(self):
        await self.restart(mode="king")
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        start1, start2 = await asyncio.gather(
            self.join(r1, w1, "A"), self.join(r2, w2, "B"),
        )
        self.assertEqual(start1["mode"], "king")
        self.assertEqual(start1["mode_state"]["target_score"], 100)
        self.assertEqual(start2["mode"], "king")
        state1, state2 = await asyncio.gather(
            self.read_until(r1, "state"), self.read_until(r2, "state"),
        )
        self.assertEqual(state1["mode"], "king")
        self.assertEqual(state1["mode_state"]["target_score"], 100)
        self.assertIn("mode_state", state2)

    async def test_lobby_advertises_next_rotation_mode(self):
        rs, ws = await self.connect()
        await self.send(ws, {"type": "spectate"})
        await self.read_until(rs, "spectating")
        r1, w1 = await self.connect()
        await self.send(w1, {"type": "join", "protocol": 1, "name": "A"})
        await self.read_until(r1, "joined")
        lobby = await self.read_until(rs, "lobby")
        self.assertEqual(lobby["mode"], "classic")
        self.assertEqual(lobby["mode_label"], "Classic")
        self.assertTrue(lobby["mode_description"])
        self.assertIsNone(lobby["starts_in_ms"])

    async def test_fixed_team_waits_for_four_players(self):
        await self.restart(mode="team")
        rs, ws = await self.connect()
        await self.send(ws, {"type": "spectate"})
        await self.read_until(rs, "spectating")

        players = []
        for index in range(1, 4):
            reader, writer = await self.connect()
            players.append((reader, writer))
            await self.send(writer, {
                "type": "join", "protocol": 1, "name": f"T{index}",
            })
            await self.read_until(reader, "joined")
            lobby = await self.read_until(rs, "lobby")
            self.assertEqual(len(lobby["players"]), index)
            self.assertEqual(lobby["mode"], "team")
            self.assertIsNone(lobby["starts_in_ms"])
            self.assertIsNone(self.server.match)

        reader, writer = await self.connect()
        players.append((reader, writer))
        await self.send(writer, {"type": "join", "protocol": 1, "name": "T4"})
        start = await self.read_until(reader, "start")
        self.assertEqual(start["mode"], "team")
        self.assertEqual(len(start["players"]), 4)

    async def test_protocol_name_validation_uniqueness_and_ping(self):
        reader, writer = await self.connect()
        await self.send(writer, {"type": "ping", "ts": 123})
        pong = await self.read_until(reader, "pong")
        self.assertEqual(pong["ts"], 123)

        writer.write(b"not-json\n")
        await writer.drain()
        self.assertEqual((await self.read_until(reader, "error"))["code"],
                         "bad_json")
        await self.send(writer, [])
        self.assertEqual((await self.read_until(reader, "error"))["code"],
                         "invalid_message")
        await self.send(writer, {"type": "join", "protocol": 2, "name": "A"})
        self.assertEqual((await self.read_until(reader, "error"))["code"],
                         "protocol_mismatch")
        for invalid in ("   ", "x" * 21, "bad\x00name"):
            await self.send(writer, {"type": "join", "protocol": 1,
                                     "name": invalid})
            self.assertEqual((await self.read_until(reader, "error"))["code"],
                             "invalid_name")

        await self.send(writer, {"type": "join", "protocol": 1, "name": "Same"})
        self.assertEqual((await self.read_until(reader, "joined"))["name"],
                         "Same")
        await self.send(writer, {"type": "join", "protocol": 1, "name": "Again"})
        self.assertEqual((await self.read_until(reader, "error"))["code"],
                         "already_joined")

        reader2, writer2 = await self.connect()
        await self.send(writer2, {"type": "join", "protocol": 1, "name": "same"})
        joined2 = await self.read_until(reader2, "joined")
        self.assertEqual(joined2["name"], "same-2")

    async def test_two_player_rotation_skips_team_across_matches(self):
        await self.restart(tick_ms=50, min_turn_ms=0, turn_limit=1,
                           lobby_wait_ms=10)
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        for expected_mode in ("classic", "king", "survival", "bounty"):
            await asyncio.gather(
                self.send(w1, {"type": "join", "protocol": 1, "name": "A"}),
                self.send(w2, {"type": "join", "protocol": 1, "name": "B"}),
            )
            starts = await asyncio.gather(
                self.read_until(r1, "start"), self.read_until(r2, "start"),
            )
            self.assertEqual(starts[0]["mode"], expected_mode)
            self.assertEqual(starts[1]["mode"], expected_mode)
            await asyncio.gather(self.read_until(r1, "end"),
                                 self.read_until(r2, "end"))

    async def test_action_turn_must_be_an_integer(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        await asyncio.gather(self.join(r1, w1, "A"), self.join(r2, w2, "B"))
        await self.send(w1, {"type": "action", "turn": True,
                             "action": {"type": "wait"}})
        error = await self.read_until(r1, "error")
        self.assertEqual(error["code"], "invalid_message")

    async def test_rate_limit_returns_error_without_closing(self):
        reader, writer = await self.connect()
        payload = b"".join(
            (json.dumps({"type": "ping", "ts": index}) + "\n").encode()
            for index in range(65)
        )
        with patch("arena_server.tcp_gateway.RATE_PER_SECOND", 0.0):
            writer.write(payload)
            await writer.drain()

            async def collect():
                return [await self.read_json(reader) for _ in range(65)]

            messages = await asyncio.wait_for(collect(), 3)
        pongs = sum(msg["type"] == "pong" for msg in messages)
        limited = sum(msg.get("code") == "rate_limited" for msg in messages)
        self.assertGreaterEqual(pongs, 30)
        self.assertGreaterEqual(limited, 1)
        await asyncio.sleep(0.1)
        await self.send(writer, {"type": "ping", "ts": "after"})
        self.assertEqual((await self.read_until(reader, "pong"))["ts"], "after")

    async def test_max_clients_rejects_and_closes_excess_connection(self):
        await self.restart(max_clients=1)
        await self.connect()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)
        self.writers.append(writer)
        error = await self.read_json(reader)
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "server_full")
        line = await asyncio.wait_for(reader.readline(), 3)
        self.assertEqual(line, b"")

    async def test_all_submit_resolves_early_after_min_turn(self):
        await self.restart(tick_ms=1000, min_turn_ms=120, turn_limit=1)
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        await asyncio.gather(self.join(r1, w1, "A"), self.join(r2, w2, "B"))
        await asyncio.gather(self.read_until(r1, "state"),
                             self.read_until(r2, "state"))
        started = time.monotonic()
        await asyncio.gather(
            self.send(w1, {"type": "action", "turn": 1,
                           "action": {"type": "wait"}}),
            self.send(w2, {"type": "action", "turn": 1,
                           "action": {"type": "wait"}}),
        )
        await asyncio.gather(self.read_until(r1, "action_ack"),
                             self.read_until(r2, "action_ack"))
        ends = await asyncio.gather(self.read_until(r1, "end"),
                                    self.read_until(r2, "end"))
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.08)
        self.assertLess(elapsed, 0.85)
        self.assertEqual(ends[0]["reason"], "turn_limit")

    async def test_tick_deadline_and_complete_mode_aware_jsonl(self):
        with tempfile.TemporaryDirectory() as log_dir:
            await self.restart(tick_ms=180, min_turn_ms=0, turn_limit=1,
                               max_missed_turns=2, no_logs=False,
                               log_dir=log_dir)
            r1, w1 = await self.connect()
            r2, w2 = await self.connect()
            await asyncio.gather(self.join(r1, w1, "A"), self.join(r2, w2, "B"))
            started = time.monotonic()
            await asyncio.gather(self.read_until(r1, "state"),
                                 self.read_until(r2, "state"))
            ends = await asyncio.gather(self.read_until(r1, "end"),
                                        self.read_until(r2, "end"))
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.12)
            self.assertEqual(ends[0]["reason"], "turn_limit")
            await self.server.stop()

            files = list(Path(log_dir).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            records = [json.loads(line) for line in
                       files[0].read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["type"] for record in records],
                             ["start", "state", "end"])
            for record in records:
                self.assertEqual(record["mode"], "classic")
                self.assertIn("mode_state", record)
                self.assertEqual(record["match_id"], ends[0]["match_id"])

    async def test_end_log_failures_still_deliver_end_and_release_match(self):
        class FailingEndLog:
            def __init__(self):
                self.close_attempts = 0

            def write(self, message):
                if message["type"] == "end":
                    raise OSError("end write failed")

            def close(self):
                self.close_attempts += 1
                if self.close_attempts == 2:
                    raise OSError("close failed")

        log = FailingEndLog()
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch(
            "arena_server.server.NullLog", return_value=log,
        ):
            await self.restart(tick_ms=1000, min_turn_ms=0, turn_limit=1)
            r1, w1 = await self.connect()
            r2, w2 = await self.connect()
            await asyncio.gather(self.join(r1, w1, "A"),
                                 self.join(r2, w2, "B"))
            match_task = self.server._match_task
            ends = await asyncio.gather(self.play_waits(r1, w1),
                                        self.play_waits(r2, w2))
            results = await asyncio.gather(match_task, return_exceptions=True)
            # Do not let teardown repeat the injected close failure.
            log.close_attempts = 2

        self.assertEqual([end["reason"] for end in ends],
                         ["turn_limit", "turn_limit"])
        self.assertEqual(results, [None])
        self.assertIsNone(self.server.match)
        self.assertIn("OSError: end write failed", stderr.getvalue())
        self.assertIn("OSError: close failed", stderr.getvalue())

    async def test_graceful_stop_closes_connections_and_is_idempotent(self):
        reader, writer = await self.connect()
        await self.server.stop()
        await self.server.stop()
        line = await asyncio.wait_for(reader.readline(), 3)
        self.assertEqual(line, b"")
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
