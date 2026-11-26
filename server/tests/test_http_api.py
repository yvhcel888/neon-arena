import asyncio
import json
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from arena_server.config import ServerConfig
from arena_server.http_api import HttpApi, HttpRequest
from arena_server.participants import Participant
from arena_server.protocol import ServerFull
from arena_server.server import GameServer
from arena_server.sessions import SessionManager


class SessionManagerTests(unittest.TestCase):
    def test_tokens_are_urlsafe_and_use_24_random_bytes(self):
        manager = SessionManager()
        participant = Participant("Alice", "human", "http")
        with patch("arena_server.sessions.secrets.token_urlsafe",
                   return_value="fixed-token") as token_urlsafe:
            session = manager.create(participant)
        token_urlsafe.assert_called_once_with(24)
        self.assertEqual(session.token, "fixed-token")
        self.assertIs(session.participant, participant)
        self.assertIs(participant.session, session)
        self.assertIs(manager.get("fixed-token"), session)
        self.assertEqual(len(manager), 1)

        manager.drop("fixed-token")
        self.assertIsNone(manager.get("fixed-token"))
        self.assertEqual(len(manager), 0)

    def test_real_tokens_are_unique_and_urlsafe(self):
        manager = SessionManager()
        sessions = [manager.create(Participant(str(index), "human", "http"))
                    for index in range(20)]
        tokens = {session.token for session in sessions}
        self.assertEqual(len(tokens), 20)
        for token in tokens:
            self.assertRegex(token, r"^[A-Za-z0-9_-]{32}$")

    def test_cleanup_returns_expired_sessions_without_mutating_game_state(self):
        manager = SessionManager()
        now = time.monotonic()
        lobby = manager.create(Participant("Lobby", "human", "http"))
        lobby.last_poll = now - 30
        retained_lobby = manager.create(Participant("Fresh", "human", "http"))
        retained_lobby.last_poll = now - 30
        expired_lobby = manager.create(Participant("Old", "human", "http"))
        expired_lobby.last_poll = now - 30.001

        ended = manager.create(Participant("Ended", "human", "http"))
        ended.participant.state = "idle"
        ended.ended_result = {"reason": "turn_limit"}
        ended.ended_at = now - 600
        retained_end = manager.create(Participant("Recent", "human", "http"))
        retained_end.participant.state = "idle"
        retained_end.ended_result = {"reason": "turn_limit"}
        retained_end.ended_at = now - 600
        expired_end = manager.create(Participant("Ancient", "human", "http"))
        expired_end.participant.state = "idle"
        expired_end.ended_result = {"reason": "turn_limit"}
        expired_end.ended_at = now - 600.001

        expired = manager.cleanup(now)
        self.assertEqual({session.token for session in expired},
                         {expired_lobby.token, expired_end.token})
        self.assertEqual(len(manager), 6)
        self.assertEqual(expired_lobby.participant.state, "lobby")
        self.assertIs(expired_lobby.participant.session, expired_lobby)
        self.assertIs(manager.get(lobby.token), lobby)
        self.assertIs(manager.get(retained_lobby.token), retained_lobby)
        self.assertIs(manager.get(ended.token), ended)
        self.assertIs(manager.get(retained_end.token), retained_end)

    def test_rate_window_keeps_at_most_twenty_requests_per_second(self):
        manager = SessionManager()
        session = manager.create(Participant("Rate", "human", "http"))
        self.assertTrue(all(manager.allow_request(session, 100.0)
                            for _ in range(20)))
        self.assertFalse(manager.allow_request(session, 100.5))
        self.assertTrue(manager.allow_request(session, 101.0))
        self.assertEqual(len(session.requests), 1)


class HttpHarness(unittest.IsolatedAsyncioTestCase):
    def make_server(self, **overrides):
        values = {
            "host": "127.0.0.1", "tcp_port": 0, "api_port": 0,
            "tick_ms": 400, "min_turn_ms": 0, "turn_limit": 2,
            "lobby_wait_ms": 30, "seed": 5, "no_logs": True,
        }
        values.update(overrides)
        return GameServer(ServerConfig(**values))

    async def asyncSetUp(self):
        self.server = self.make_server()
        self.writers = []
        await self.restart()

    async def restart(self, **overrides):
        if getattr(self, "server", None) is not None:
            await self.server.stop()
        self.server = self.make_server(**overrides)
        self.tcp_port, self.api_port = await self.server.start()
        self.assertIsInstance(self.tcp_port, int)
        self.assertGreater(self.tcp_port, 0)
        self.assertIsInstance(self.api_port, int)
        self.assertGreater(self.api_port, 0)
        self.assertIsInstance(self.server.http, HttpApi)
        self.base = f"http://127.0.0.1:{self.api_port}/api/v1"

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        await self.server.stop()

    def _request(self, method, path, body=None, token=None, headers=None,
                 raw_body=None):
        data = (json.dumps(body).encode("utf-8") if body is not None
                else raw_body)
        req = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers or {},
        )
        if body is not None or raw_body is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                payload = json.loads(resp.read() or b"{}")
                return (resp.status, payload,
                        {k.lower(): v for k, v in resp.headers.items()})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            payload = json.loads(raw) if raw else {}
            return (exc.code, payload,
                    {k.lower(): v for k, v in exc.headers.items()})

    async def request(self, method, path, **kwargs):
        return await asyncio.to_thread(
            self._request, method, path, **kwargs,
        )

    async def raw_request(self, request: bytes):
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.api_port,
        )
        self.writers.append(writer)
        writer.write(request)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), 3)
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        status = int(lines[0].split(b" ", 2)[1])
        headers = {}
        for line in lines[1:]:
            key, _, value = line.partition(b":")
            headers[key.decode("ascii").lower()] = value.strip().decode("ascii")
        payload = json.loads(body) if body else {}
        return status, payload, headers

    async def create_session(self, name):
        status, data, _ = await self.request(
            "POST", "/sessions", body={"name": name},
        )
        self.assertEqual(status, 200, data)
        return data["token"], data["view"]

    async def wait_for_mode(self, token, wanted, timeout=8):
        deadline = asyncio.get_running_loop().time() + timeout
        view = None
        while asyncio.get_running_loop().time() < deadline:
            status, data, _ = await self.request("GET", "/state", token=token)
            self.assertEqual(status, 200, data)
            view = data["view"]
            if view["mode"] == wanted:
                return view
            await asyncio.sleep(0.02)
        self.fail(f"session did not reach {wanted!r}; last view={view!r}")

    async def test_http_handler_limit_rejects_second_idle_connection(self):
        await self.restart(max_clients=1, tick_ms=5000, lobby_wait_ms=5000)
        first_reader, first_writer = await asyncio.open_connection(
            "127.0.0.1", self.api_port,
        )
        self.writers.append(first_writer)
        deadline = asyncio.get_running_loop().time() + 1
        while len(self.server.http._handlers) < 1:
            self.assertLess(asyncio.get_running_loop().time(), deadline)
            await asyncio.sleep(0)

        status, data, headers = await self.raw_request(
            b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        )
        self.assertEqual(status, 503)
        self.assertEqual(data["error"]["code"], "server_full")
        self.assertEqual(headers["connection"], "close")
        self.assertEqual(len(self.server.http._handlers), 1)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(first_reader.read(), 0.05)

    async def test_stop_cancels_delayed_handler_without_late_response(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        request = HttpRequest("GET", "/api/v1/health", {}, b"")

        async def delayed_request(reader):
            entered.set()
            try:
                await release.wait()
            finally:
                await asyncio.sleep(0)
                cancelled.set()
            return request

        with patch.object(self.server.http, "_read_request",
                          new=delayed_request):
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", self.api_port,
            )
            self.writers.append(writer)
            writer.write(b"GET /api/v1/health HTTP/1.1\r\n\r\n")
            await writer.drain()
            await asyncio.wait_for(entered.wait(), 1)
            stop_task = asyncio.create_task(self.server.stop())
            try:
                await asyncio.sleep(0)
                self.assertFalse(stop_task.done())
                await asyncio.wait_for(cancelled.wait(), 1)
                await asyncio.wait_for(stop_task, 1)
                self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
                self.assertFalse(self.server.http._handlers)
                self.assertFalse(self.server.http._writers)
            finally:
                release.set()
                if not stop_task.done():
                    stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)

    async def test_health_rules_cors_and_unknown_path(self):
        status, data, headers = await self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["protocol"], 1)
        self.assertEqual(data["server"], "Neon Arena")
        self.assertEqual(data["lobby_players"], 0)
        self.assertFalse(data["match_running"])
        self.assertEqual(data["active_players"], 0)
        self.assertEqual(data["spectators"], 0)
        self.assertGreaterEqual(data["uptime_s"], 0)
        self.assertEqual(headers["access-control-allow-origin"], "*")
        self.assertEqual(headers["access-control-allow-methods"],
                         "GET, POST, DELETE, OPTIONS")
        self.assertEqual(headers["access-control-allow-headers"],
                         "Authorization, Content-Type")
        self.assertEqual(headers["access-control-max-age"], "600")
        self.assertEqual(headers["connection"], "close")
        self.assertEqual(headers["content-type"],
                         "application/json; charset=utf-8")

        status, data, _ = await self.request("GET", "/rules")
        self.assertEqual(status, 200)
        self.assertIn("attack", data["rules"])
        self.assertEqual(data["defaults"]["mode"], "rotation")
        self.assertEqual(data["defaults"]["tick_ms"], 400)

        status, data, headers = await self.request("GET", "/")
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "not_found")
        self.assertEqual(headers["access-control-allow-origin"], "*")

        status, data, _ = await self.request("POST", "/")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "not_found")
        status, data, _ = await self.request("POST", "/health")
        self.assertEqual(status, 405)
        self.assertEqual(data["error"]["code"], "method_not_allowed")

        status, data, headers = await self.request("GET", "/../client/index.html")
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])
        self.assertNotIn("html", headers["content-type"])

        status, _, headers = await self.request(
            "OPTIONS", "/sessions",
            headers={"Origin": "http://127.0.0.1:8090",
                     "Access-Control-Request-Method": "POST"},
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers["access-control-allow-origin"], "*")

    async def test_session_auth_state_and_delete(self):
        token, view = await self.create_session("Alice")
        self.assertEqual(view["mode"], "lobby")
        self.assertEqual(view["you"]["name"], "Alice")
        self.assertEqual(view["you"]["kind"], "human")
        self.assertIsNone(view["you"]["id"])
        self.assertIn("mode", view["lobby"])
        self.assertIn("mode_label", view["lobby"])
        self.assertIn("mode_description", view["lobby"])

        status, data, headers = await self.request("GET", "/state")
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "unauthorized")
        self.assertEqual(headers["access-control-allow-origin"], "*")

        status, data, _ = await self.request("GET", "/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["view"]["mode"], "lobby")

        status, data, _ = await self.request("DELETE", "/sessions", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data, {"ok": True})
        status, data, _ = await self.request("GET", "/state", token=token)
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "unauthorized")
        self.assertEqual(self.server.client_count(), 0)

    async def test_session_creation_recovery_and_invalid_token_rules(self):
        await self.restart(tick_ms=5000, lobby_wait_ms=5000)
        token, first_view = await self.create_session("Same")
        status, data, _ = await self.request("POST", "/sessions", token=token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["token"], token)
        self.assertEqual(data["view"]["you"], first_view["you"])
        self.assertEqual(len(self.server.sessions), 1)

        status, data, _ = await self.request(
            "POST", "/sessions", token="not-a-token",
        )
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "unauthorized")

        status, data, _ = await self.request(
            "POST", "/sessions", token="not-a-token", body={"name": "New"},
        )
        self.assertEqual(status, 200, data)
        self.assertNotEqual(data["token"], "not-a-token")
        self.assertEqual(data["view"]["you"]["name"], "New")

        for name in (None, "", "x" * 21, "bad\x00name"):
            body = {} if name is None else {"name": name}
            status, data, _ = await self.request("POST", "/sessions", body=body)
            self.assertEqual(status, 400, body)
            self.assertEqual(data["error"]["code"], "invalid_name")

        status, data, _ = await self.request(
            "POST", "/sessions", raw_body=b"{not-json",
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "invalid_json")

    async def test_deeply_nested_json_is_invalid_without_stack_logging(self):
        body = (b'{"name":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}")
        with patch("arena_server.http_api.LOGGER.exception") as log_exception:
            status, data, _ = await self.request(
                "POST", "/sessions", raw_body=body,
            )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "invalid_json")
        log_exception.assert_not_called()

    async def test_two_waiting_players_expose_next_mode_metadata(self):
        await self.restart(tick_ms=5000, lobby_wait_ms=5000)
        token_a, _ = await self.create_session("A")
        await self.create_session("B")
        view = await self.wait_for_mode(token_a, "lobby")
        self.assertEqual(len(view["lobby"]["players"]), 2)
        self.assertEqual(view["lobby"]["mode"], "classic")
        self.assertEqual(view["lobby"]["mode_label"], "Classic")
        self.assertTrue(view["lobby"]["mode_description"])
        deadline = asyncio.get_running_loop().time() + 1
        while (view["lobby"]["starts_in_ms"] is None
               and asyncio.get_running_loop().time() < deadline):
            await asyncio.sleep(0.02)
            view = await self.wait_for_mode(token_a, "lobby")
        self.assertIsNotNone(view["lobby"]["starts_in_ms"])
        self.assertIsNone(self.server.match)

    async def test_mixed_tcp_agent_and_http_human_finish_match(self):
        await self.restart(tick_ms=5000, turn_limit=2, lobby_wait_ms=30)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.tcp_port,
        )
        self.writers.append(writer)
        welcome = json.loads(await asyncio.wait_for(reader.readline(), 3))
        self.assertEqual(welcome["type"], "welcome")
        writer.write((json.dumps({"type": "join", "protocol": 1,
                                  "name": "Agent-A"}) + "\n").encode())
        await writer.drain()

        token, view = await self.create_session("Human-H")

        async def drive_agent():
            last_turn = -1
            while True:
                line = await asyncio.wait_for(reader.readline(), 5)
                self.assertTrue(line, "agent connection closed")
                msg = json.loads(line)
                if msg["type"] == "state" and msg["turn"] != last_turn:
                    last_turn = msg["turn"]
                    writer.write((json.dumps({
                        "type": "action", "turn": msg["turn"],
                        "action": {"type": "wait"},
                    }) + "\n").encode())
                    await writer.drain()
                if msg["type"] == "end":
                    return msg

        agent_task = asyncio.create_task(drive_agent())
        final_view = None
        try:
            deadline = asyncio.get_running_loop().time() + 20
            while asyncio.get_running_loop().time() < deadline:
                status, data, _ = await self.request(
                    "GET", "/state", token=token,
                )
                self.assertEqual(status, 200, data)
                final_view = data["view"]
                if final_view["mode"] == "match":
                    match = final_view["match"]
                    self.assertEqual({p["kind"] for p in match["players"]},
                                     {"agent", "human"})
                    self.assertIn(match["mode"],
                                  {"classic", "king", "survival", "bounty"})
                    self.assertIn("mode_state", match)
                    for key in ("match_id", "seed", "turn", "turn_limit",
                                "tick_ms", "reply_by_ms", "rules", "arena",
                                "players", "nodes", "events_turn", "events",
                                "submitted", "your_action"):
                        self.assertIn(key, match)
                    if not match["submitted"]:
                        status, _, _ = await self.request(
                            "POST", "/actions", token=token,
                            body={"turn": match["turn"],
                                  "action": {"type": "wait"}},
                        )
                        self.assertEqual(status, 200)
                elif final_view["mode"] == "ended":
                    break
                await asyncio.sleep(0.03)

            self.assertIsNotNone(final_view)
            self.assertEqual(final_view["mode"], "ended")
            result = final_view["result"]
            self.assertIn(result["reason"],
                          {"last_standing", "turn_limit",
                           "mutual_destruction", "score_limit"})
            self.assertIn(result["mode"],
                          {"classic", "king", "survival", "bounty"})
            self.assertIn("mode_state", result)
            self.assertEqual(len(result["standings"]), 2)
            self.assertEqual(final_view["match"]["mode"], result["mode"])
            self.assertIn("mode_state", final_view["match"])
            session = self.server.sessions.get(token)
            self.assertIsNotNone(session.ended_result)
            self.assertIsNotNone(session.ended_match)
            self.assertIsNotNone(session.ended_at)
            self.assertEqual(session.ended_result, result)
            end = await asyncio.wait_for(agent_task, 5)
            self.assertEqual(end["match_id"], result["match_id"])
        finally:
            if not agent_task.done():
                agent_task.cancel()
                await asyncio.gather(agent_task, return_exceptions=True)

    async def test_forfeit_http_view_uses_current_turn_for_state_and_events(self):
        await self.restart(tick_ms=5000, min_turn_ms=0, turn_limit=3,
                           lobby_wait_ms=5)
        tokens = []
        for name in ("A", "B", "C"):
            token, _ = await self.create_session(name)
            tokens.append(token)
        views = await asyncio.gather(*(
            self.wait_for_mode(token, "match") for token in tokens
        ))
        turn = views[0]["match"]["turn"]
        self.assertEqual(turn, 1)
        results = await asyncio.gather(*(
            self.request("POST", "/actions", token=token,
                         body={"turn": turn, "action": {"type": "wait"}})
            for token in tokens
        ))
        self.assertTrue(all(status == 200 for status, _, _ in results), results)

        async def wait_for_turn(token, wanted):
            deadline = asyncio.get_running_loop().time() + 3
            view = None
            while asyncio.get_running_loop().time() < deadline:
                status, data, _ = await self.request(
                    "GET", "/state", token=token,
                )
                self.assertEqual(status, 200, data)
                view = data["view"]
                if (view["mode"] == "match"
                        and view["match"]["turn"] == wanted):
                    return view
                await asyncio.sleep(0)
            self.fail(f"session did not reach turn {wanted}; last view={view!r}")

        resolved = await wait_for_turn(tokens[0], 2)
        match = self.server.match
        self.assertIsNotNone(match)
        self.assertEqual(match.engine.completed_turns, 1)
        self.assertEqual(match.engine.turn, 2)

        status, _, _ = await self.request(
            "DELETE", "/sessions", token=tokens[2],
        )
        self.assertEqual(status, 200)
        self.assertIs(self.server.match, match)
        self.assertFalse(match.engine.finished)

        forfeit_views = await asyncio.gather(*(
            self.request("GET", "/state", token=token)
            for token in tokens[:2]
        ))
        for status, data, _ in forfeit_views:
            self.assertEqual(status, 200, data)
            view = data["view"]
            self.assertEqual(view["mode"], "match")
            state = view["match"]
            self.assertEqual(state["turn"], 2)
            self.assertEqual(state["events_turn"], 2)
            self.assertEqual(state["events"],
                             [{"type": "forfeit", "player": "P3"}])
            leaver = next(player for player in state["players"]
                          if player["id"] == "P3")
            self.assertFalse(leaver["alive"])
            self.assertTrue(leaver["stats"]["forfeited"])

        results = await asyncio.gather(*(
            self.request("POST", "/actions", token=token,
                         body={"turn": 2, "action": {"type": "wait"}})
            for token in tokens[:2]
        ))
        self.assertTrue(all(status == 200 for status, _, _ in results), results)
        post_forfeit = await wait_for_turn(tokens[0], 3)
        state = post_forfeit["match"]
        self.assertEqual(state["events_turn"], 2)
        self.assertFalse(any(event["type"] == "forfeit"
                             for event in state["events"]))

    async def test_ended_session_can_requeue_and_clears_frozen_result(self):
        await self.restart(tick_ms=5000, turn_limit=1, lobby_wait_ms=5)
        token_a, _ = await self.create_session("A")
        token_b, _ = await self.create_session("B")
        first = await self.wait_for_mode(token_a, "match")
        second = await self.wait_for_mode(token_b, "match")
        status, _, _ = await self.request(
            "POST", "/actions", token=token_a,
            body={"turn": first["match"]["turn"],
                  "action": {"type": "wait"}},
        )
        self.assertEqual(status, 200)
        status, _, _ = await self.request(
            "POST", "/actions", token=token_b,
            body={"turn": second["match"]["turn"],
                  "action": {"type": "wait"}},
        )
        self.assertEqual(status, 200)
        await self.wait_for_mode(token_a, "ended")
        session = self.server.sessions.get(token_a)
        self.assertIsNotNone(session.ended_result)

        status, data, _ = await self.request("POST", "/sessions", token=token_a)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["token"], token_a)
        self.assertIn(data["view"]["mode"], {"lobby", "match"})
        self.assertIsNone(session.ended_result)
        self.assertIsNone(session.ended_match)
        self.assertIsNone(session.ended_at)
        self.assertIsNone(session.participant.player_id)
        self.assertIn(session.participant, self.server.lobby.waiting)

    async def test_action_error_status_mapping(self):
        await self.restart(tick_ms=10000, turn_limit=5, lobby_wait_ms=5)
        token, _ = await self.create_session("Human")
        status, data, _ = await self.request(
            "POST", "/actions", token=token,
            body={"turn": 1, "action": {"type": "wait"}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error"]["code"], "not_in_match")
        await self.create_session("Agent")

        view = await self.wait_for_mode(token, "match")
        turn = view["match"]["turn"]
        session = self.server.sessions.get(token)
        match = session.participant.match
        player = match.engine.players[session.participant.player_id]

        async def expect(status_code, code, action, action_turn=turn):
            result, payload, _ = await self.request(
                "POST", "/actions", token=token,
                body={"turn": action_turn, "action": action},
            )
            self.assertEqual(result, status_code, payload)
            self.assertEqual(payload["error"]["code"], code)

        await expect(400, "no_active_node", {"type": "gather"})
        await expect(400, "full_hp", {"type": "heal"})
        player.shield = match.engine.rules.max_shield
        await expect(400, "shield_full", {"type": "shield"})
        player.energy = 0
        await expect(400, "insufficient_energy",
                     {"type": "attack", "dir": "n"})
        player.energy = match.engine.rules.start_energy
        if player.pos[0] == 1:
            wall_action = {"type": "move", "dir": "w"}
        elif player.pos[1] == 1:
            wall_action = {"type": "move", "dir": "n"}
        else:
            wall_action = {"type": "move", "dir": "e"}
        await expect(400, "wall", wall_action)
        await expect(400, "invalid_action", {"type": "unknown"})
        await expect(409, "stale_turn", {"type": "wait"}, turn + 1)

        status, data, _ = await self.request(
            "POST", "/actions", token=token,
            body={"turn": True, "action": {"type": "wait"}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "invalid_action")

        match.closed = True
        await expect(409, "turn_closed", {"type": "wait"})
        match.closed = False
        player.alive = False
        await expect(409, "not_alive", {"type": "wait"})

    async def test_rate_limit_and_server_full_errors(self):
        token, _ = await self.create_session("Rate")
        allow_request = self.server.sessions.allow_request
        fixed_now = time.monotonic()
        with patch.object(
            self.server.sessions, "allow_request",
            side_effect=lambda session, now: allow_request(session, fixed_now),
        ):
            results = await asyncio.gather(*(
                self.request("GET", "/state", token=token) for _ in range(25)
            ))
        statuses = [status for status, _, _ in results]
        self.assertGreaterEqual(statuses.count(429), 1)
        self.assertLessEqual(statuses.count(200), 20)
        for status, data, headers in results:
            self.assertEqual(headers["access-control-allow-origin"], "*")
            if status == 429:
                self.assertEqual(data["error"]["code"], "rate_limited")

        limited = self.server.sessions.get(token)
        limited.requests.clear()
        limited.requests.extend([time.monotonic()] * 20)
        status, data, _ = await self.request(
            "POST", "/sessions", token=token, raw_body=b"{not-json",
        )
        self.assertEqual(status, 429)
        self.assertEqual(data["error"]["code"], "rate_limited")

        await self.restart(max_clients=1, tick_ms=5000, lobby_wait_ms=5000)
        await self.create_session("Only")
        status, data, _ = await self.request(
            "POST", "/sessions", body={"name": "Excess"},
        )
        self.assertEqual(status, 503)
        self.assertEqual(data["error"]["code"], "server_full")

    async def test_restricted_cors_echoes_only_allowed_origin(self):
        await self.restart(
            cors_origin="http://one.example, http://two.example",
            tick_ms=5000, lobby_wait_ms=5000,
        )
        status, _, headers = await self.request(
            "GET", "/health", headers={"Origin": "http://one.example"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["access-control-allow-origin"],
                         "http://one.example")
        status, _, headers = await self.request(
            "GET", "/health", headers={"Origin": "http://evil.example"},
        )
        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)
        status, _, headers = await self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)

        status, _, headers = await self.raw_request(
            b"POST /api/v1/sessions HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nOrigin: http://one.example\r\n"
            b"Content-Length: 32769\r\n\r\n"
        )
        self.assertEqual(status, 413)
        self.assertEqual(headers["access-control-allow-origin"],
                         "http://one.example")

    async def test_oversized_headers_preserve_allowed_origin_after_padding(self):
        await self.restart(
            cors_origin="http://allowed.example",
            tick_ms=5000, lobby_wait_ms=5000,
        )
        status, data, headers = await self.raw_request(
            b"GET /api/v1/health HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nX-Pad: "
            + b"x" * (18 * 1024)
            + b"\r\nOrigin: http://allowed.example\r\nX-Tail: "
            + b"y" * (20 * 1024)
            + b"\r\n\r\n"
        )
        self.assertEqual(status, 431)
        self.assertEqual(data["error"]["code"], "headers_too_large")
        self.assertEqual(headers.get("access-control-allow-origin"),
                         "http://allowed.example")

    async def test_expired_session_cleanup_removes_lobby_and_ended_sessions(self):
        token, _ = await self.create_session("Stale")
        session = self.server.sessions.get(token)
        participant = session.participant
        now = time.monotonic()
        session.last_poll = now - 31
        await self.server._cleanup_sessions(now)
        self.assertIsNone(self.server.sessions.get(token))
        self.assertIsNone(participant.session)
        self.assertEqual(participant.state, "idle")
        self.assertNotIn(participant, self.server.lobby.waiting)

        ended_token, _ = await self.create_session("Ended")
        ended = self.server.sessions.get(ended_token)
        ended.participant.state = "idle"
        ended.ended_result = {"reason": "turn_limit"}
        ended.ended_at = now - 601
        self.server.lobby.remove(ended.participant)
        await self.server._cleanup_sessions(now)
        self.assertIsNone(self.server.sessions.get(ended_token))
        self.assertIsNone(ended.participant.session)

    async def test_failed_requeue_preserves_ended_session(self):
        await self.restart(tick_ms=5000, lobby_wait_ms=5000, max_players=2)
        token, _ = await self.create_session("Ended")
        session = self.server.sessions.get(token)
        participant = session.participant
        self.server.lobby.remove(participant)
        participant.state = "idle"
        participant.player_id = "P1"
        session.ended_result = {"reason": "turn_limit"}
        session.ended_match = {"match_id": "frozen"}
        session.ended_at = time.monotonic()
        self.server.lobby.waiting.extend([
            Participant("Waiting-A", "human", "http"),
            Participant("Waiting-B", "agent", "tcp"),
        ])
        with self.assertRaises(ServerFull):
            await self.server.requeue(participant)
        self.assertEqual(participant.state, "idle")
        self.assertEqual(participant.player_id, "P1")
        self.assertEqual(session.ended_result, {"reason": "turn_limit"})
        self.assertEqual(session.ended_match, {"match_id": "frozen"})
        self.assertIsNotNone(session.ended_at)

    async def test_http_parser_limits_methods_and_chunked_rejection(self):
        request = (
            b"PUT /api/v1/health HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n"
        )
        status, data, headers = await self.raw_request(request)
        self.assertEqual(status, 405)
        self.assertFalse(data["ok"])
        self.assertEqual(headers["access-control-allow-origin"], "*")

        token, _ = await self.create_session("Header")
        status, data, _ = await self.raw_request(
            b"GET /api/v1/state HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n Authorization: Bearer "
            + token.encode("ascii")
            + b"\r\nConnection: close\r\n\r\n"
        )
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

        status, data, _ = await self.raw_request(
            b"POST /api/v1/sessions HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nContent-Length: 32769\r\n\r\n"
        )
        self.assertEqual(status, 413)
        self.assertFalse(data["ok"])

        status, data, _ = await self.raw_request(
            b"POST /api/v1/sessions HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nTransfer-Encoding: chunked\r\n\r\n"
        )
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

        status, data, _ = await self.raw_request(
            b"POST /api/v1/sessions HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nContent-Length: nope\r\n\r\n"
        )
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

        status, data, _ = await self.raw_request(
            b"POST /api/v1/sessions HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nContent-Length: \xb2\r\n\r\n"
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "invalid_content_length")

        status, data, headers = await self.raw_request(
            b"GET /api/v1/health HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nX-Pad: "
            + b"x" * (16 * 1024)
            + b"\r\nConnection: close\r\n\r\n"
        )
        self.assertEqual(status, 431)
        self.assertFalse(data["ok"])
        self.assertEqual(headers["access-control-allow-origin"], "*")

    async def test_internal_errors_hide_details_and_log_stack(self):
        token, _ = await self.create_session("Error")
        with patch.object(self.server, "view_for",
                          side_effect=RuntimeError("private-details")):
            with self.assertLogs("arena_server.http_api", level="ERROR") as logs:
                status, data, headers = await self.request(
                    "GET", "/state", token=token,
                )
        self.assertEqual(status, 500)
        self.assertEqual(data["error"]["code"], "internal_error")
        self.assertNotIn("private-details", json.dumps(data))
        self.assertEqual(headers["access-control-allow-origin"], "*")
        self.assertIn("private-details", "\n".join(logs.output))
        self.assertNotIn(token, "\n".join(logs.output))

    async def test_team_result_preserves_mode_state_and_team_standings(self):
        await self.restart(mode="team", tick_ms=5000, turn_limit=1,
                           lobby_wait_ms=10, max_players=4)
        sessions = []
        for index in range(4):
            token, _ = await self.create_session(f"Human-{index}")
            sessions.append(token)
        views = await asyncio.gather(*(
            self.wait_for_mode(token, "match") for token in sessions
        ))
        turn = views[0]["match"]["turn"]
        results = await asyncio.gather(*(
            self.request("POST", "/actions", token=token,
                         body={"turn": turn, "action": {"type": "wait"}})
            for token in sessions
        ))
        self.assertTrue(all(status == 200 for status, _, _ in results), results)
        final_view = await self.wait_for_mode(sessions[0], "ended")
        result = final_view["result"]
        self.assertEqual(result["mode"], "team")
        self.assertIn("teams", result["mode_state"])
        self.assertEqual(len(result["team_standings"]), 2)
        self.assertEqual(result["winner"]["kind"], "team")
        self.assertEqual(final_view["match"]["mode"], "team")
        self.assertIn("mode_state", final_view["match"])


if __name__ == "__main__":
    unittest.main()
