"""Asyncio NDJSON TCP gateway for agents and spectators."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import secrets
import time
import traceback

from arena_server.engine import ActionError
from arena_server.participants import Participant
from arena_server.protocol import (
    MAX_LINE_BYTES, PROTOCOL, ServerFull, make_error, validate_name,
)

RATE_PER_SECOND = 30.0
RATE_BURST = 30.0
IDLE_TIMEOUT_SECONDS = 120.0


def _encode(message: dict) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            + "\n").encode("utf-8")


class TcpConnection:
    def __init__(self, gateway, reader, writer, client_id: str):
        self.gateway = gateway
        self.server = gateway.server
        self.reader = reader
        self.writer = writer
        self.client_id = client_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.writer_task: asyncio.Task | None = None
        self.participant: Participant | None = None
        self.role: str | None = None
        self.closed = False
        self._cleaned = False
        self.last_activity = time.monotonic()
        self.tokens = RATE_BURST
        self.token_time = self.last_activity

    async def send(self, message: dict) -> None:
        if self.closed:
            raise ConnectionError("TCP connection is closed")
        # Serialize at enqueue time so later Engine mutations cannot alter a
        # queued state snapshot.
        self.queue.put_nowait(_encode(message))

    def _consume_rate_token(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.token_time
        self.token_time = now
        self.tokens = min(RATE_BURST, self.tokens + elapsed * RATE_PER_SECOND)
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True

    async def write_loop(self) -> None:
        try:
            while not self.closed:
                data = await self.queue.get()
                try:
                    if self.closed:
                        return
                    self.writer.write(data)
                    await self.writer.drain()
                finally:
                    self.queue.task_done()
        except (ConnectionError, BrokenPipeError, OSError):
            self.closed = True
            self.writer.close()

    async def read_loop(self) -> None:
        while not self.closed:
            timeout = None
            if self.participant is None:
                remaining = IDLE_TIMEOUT_SECONDS - (
                    time.monotonic() - self.last_activity
                )
                if remaining <= 0:
                    return
                timeout = remaining
            try:
                line = await asyncio.wait_for(self.reader.readline(), timeout)
            except asyncio.TimeoutError:
                if self.participant is None:
                    return
                continue
            if not line:
                return
            if len(line) > MAX_LINE_BYTES:
                return
            self.last_activity = time.monotonic()
            if not self._consume_rate_token():
                await self.send(make_error(
                    "rate_limited", "message rate limit exceeded",
                ))
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                await self.send(make_error("bad_json", "line is not valid JSON"))
                continue
            if (not isinstance(message, dict)
                    or not isinstance(message.get("type"), str)
                    or not message["type"]):
                await self.send(make_error(
                    "invalid_message", "message must be an object with a type",
                ))
                continue
            await self._route(message)

    async def _route(self, message: dict) -> None:
        message_type = message["type"]
        try:
            if message_type == "join":
                await self._join(message)
            elif message_type == "spectate":
                await self._spectate()
            elif message_type == "action":
                await self._action(message)
            elif message_type == "leave":
                await self._leave()
            elif message_type == "ping":
                pong = {"type": "pong"}
                if "ts" in message:
                    pong["ts"] = message["ts"]
                await self.send(pong)
            else:
                await self.send(make_error(
                    "invalid_message", f"unknown message type: {message_type}",
                ))
        except ActionError as exc:
            turn = message.get("turn")
            await self.send(make_error(
                exc.code, exc.message,
                turn if isinstance(turn, int) and not isinstance(turn, bool)
                else None,
            ))
        except ServerFull:
            await self.send(make_error(
                "server_full", "the server or lobby is full",
            ))
        except Exception:
            if self.server.config.verbose:
                traceback.print_exc()
            await self.send(make_error(
                "internal_error", "the server could not process the message",
            ))

    async def _join(self, message: dict) -> None:
        participant = self.participant
        if (self.role == "spectator"
                or (participant is not None
                    and participant.state in ("lobby", "playing"))):
            raise ActionError("already_joined", "connection already joined")
        protocol = message.get("protocol")
        if not isinstance(protocol, int) or isinstance(protocol, bool) \
                or protocol != PROTOCOL:
            raise ActionError("protocol_mismatch", "unsupported protocol version")
        try:
            name = validate_name(message.get("name"))
        except ValueError as exc:
            raise ActionError("invalid_name", str(exc)) from exc

        name = self.server.unique_name(name)
        participant = Participant(
            name=name, kind="agent", transport="tcp", tcp=self,
        )
        await self.server.add_to_lobby(participant)
        self.participant = participant
        self.role = "player"
        await self.send({
            "type": "joined", "protocol": PROTOCOL,
            "name": participant.name, "kind": participant.kind,
        })

    async def _spectate(self) -> None:
        participant = self.participant
        if (self.role == "spectator"
                or (participant is not None
                    and participant.state in ("lobby", "playing"))):
            raise ActionError("already_joined", "connection already joined")
        spectator = Participant(
            name="", kind="spectator", transport="tcp", tcp=self, state="idle",
        )
        self.server.spectators.add(spectator)
        self.participant = spectator
        self.role = "spectator"
        match = self.server.match
        await self.send({
            "type": "spectating", "match_running": match is not None,
        })
        if match is not None:
            start, state = match.snapshot_for_spectator()
            await self.send(start)
            await self.send(state)

    async def _action(self, message: dict) -> None:
        participant = self.participant
        if participant is None or self.role != "player":
            raise ActionError("not_joined", "join before submitting an action")
        match = participant.match
        if match is None:
            raise ActionError("not_in_match", "connection is not in a match")
        turn = message.get("turn")
        if not isinstance(turn, int) or isinstance(turn, bool):
            raise ActionError("invalid_message", "turn must be an integer")
        normalized = match.submit(participant, turn, message.get("action"))
        await self.send({
            "type": "action_ack", "turn": turn, "action": normalized,
        })

    async def _leave(self) -> None:
        participant = self.participant
        if participant is not None:
            if self.role == "spectator":
                self.server.spectators.discard(participant)
            else:
                await self.server.remove_participant(participant)
        self.participant = None
        self.role = None
        await self.send({"type": "left"})

    async def close(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        self.closed = True
        self.gateway.connections.discard(self)
        participant = self.participant
        role = self.role
        self.participant = None
        self.role = None
        self.writer.close()
        try:
            if participant is not None:
                if role == "spectator":
                    self.server.spectators.discard(participant)
                else:
                    await self.server.remove_participant(participant)
        finally:
            current = asyncio.current_task()
            if self.writer_task is not None and self.writer_task is not current:
                self.writer_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self.writer_task
            with suppress(asyncio.CancelledError, Exception):
                await self.writer.wait_closed()


class TcpGateway:
    def __init__(self, server):
        self.server = server
        self.config = server.config
        self.connections: set[TcpConnection] = set()
        self._server: asyncio.AbstractServer | None = None
        self.port: int | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle_client, self.config.host, self.config.tcp_port,
            limit=MAX_LINE_BYTES,
        )
        sockets = self._server.sockets or []
        self.port = sockets[0].getsockname()[1]
        return self.port

    async def _handle_client(self, reader, writer) -> None:
        connection = TcpConnection(
            self, reader, writer, f"c-{secrets.token_hex(2)}",
        )
        try:
            if self.server.client_count() >= self.config.max_clients:
                connection.writer_task = asyncio.create_task(
                    connection.write_loop(),
                )
                await connection.send(make_error(
                    "server_full", "the server is full",
                ))
                await connection.queue.join()
                return
            self.connections.add(connection)
            connection.writer_task = asyncio.create_task(connection.write_loop())
            await connection.send({
                "type": "welcome", "server": "Neon Arena",
                "protocol": PROTOCOL, "client_id": connection.client_id,
            })
            await connection.read_loop()
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            await connection.close()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        connections = list(self.connections)
        if connections:
            await asyncio.gather(
                *(connection.close() for connection in connections),
                return_exceptions=True,
            )
