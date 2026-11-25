"""Game server lifecycle, lobby scheduling, and transport dispatch."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
import logging
import random
import secrets
import traceback

from arena_server.config import ServerConfig
from arena_server.engine import Engine
from arena_server.lobby import Lobby
from arena_server.logging_utils import MatchLog, NullLog
from arena_server.match import Match
from arena_server.modes import (
    MODE_DESCRIPTIONS, MODE_LABELS, MODE_MIN_PLAYERS, MODE_ORDER, select_mode,
)
from arena_server.protocol import ServerFull
from arena_server.tcp_gateway import TcpGateway

LOGGER = logging.getLogger(__name__)


class GameServer:
    def __init__(self, config: ServerConfig):
        self.config = config
        if config.mode not in (*MODE_ORDER, "rotation"):
            raise ValueError(f"unknown mode: {config.mode}")
        if not 2 <= config.min_players <= config.max_players <= 4:
            raise ValueError("players must satisfy 2 <= min <= max <= 4")
        if config.mode == "team" and config.max_players < 4:
            raise ValueError("team mode requires max_players=4")
        if min(config.tick_ms, config.min_turn_ms, config.lobby_wait_ms) < 0:
            raise ValueError("timing values must not be negative")

        self.lobby = Lobby(config.min_players, config.max_players)
        self.spectators: set = set()
        self.match: Match | None = None
        self.mode_cursor = 0
        self.match_index = 0
        self.tcp_port: int | None = None
        self.api_port: int | None = None
        self.gateway: TcpGateway | None = None
        self._lobby_task: asyncio.Task | None = None
        self._match_task: asyncio.Task | None = None
        self._last_lobby_signature = None
        self._shutdown_event = asyncio.Event()
        self._started = False
        self._stopped = False

    async def start(self) -> tuple[int, int | None]:
        if self._started:
            return self.tcp_port, None
        if self._stopped:
            raise RuntimeError("a stopped GameServer cannot be restarted")
        self.gateway = TcpGateway(self)
        try:
            self.tcp_port = await self.gateway.start()
        except Exception:
            await self.gateway.stop()
            raise
        self._started = True
        self._lobby_task = asyncio.create_task(self._lobby_loop())
        LOGGER.info("Agent TCP : %s:%s", self.config.host, self.tcp_port)
        return self.tcp_port, None

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._shutdown_event.set()
        if self._lobby_task is not None:
            self._lobby_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._lobby_task
            self._lobby_task = None
        if self.gateway is not None:
            await self.gateway.stop()
        if self._match_task is not None and not self._match_task.done():
            self._match_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._match_task
        if self.match is not None:
            self.match.log.close()
            for participant in self.match.participants:
                participant.state = "idle"
                participant.match = None
            self.match = None

    async def run_forever(self) -> None:
        try:
            await self.start()
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def _mode_for_waiting(self) -> tuple[str, int, int]:
        mode_name, next_cursor = select_mode(
            self.config.mode, len(self.lobby.waiting), self.mode_cursor,
        )
        required = max(self.config.min_players, MODE_MIN_PLAYERS[mode_name])
        return mode_name, next_cursor, required

    def lobby_view(self) -> dict:
        mode_name, _, required = self._mode_for_waiting()
        snapshot = self.lobby.snapshot(
            mode=mode_name,
            mode_label=MODE_LABELS[mode_name],
            mode_description=MODE_DESCRIPTIONS[mode_name],
            min_players=required,
        )
        return {"type": "lobby", **snapshot}

    @staticmethod
    def _lobby_signature(view: dict) -> tuple:
        countdown = view["starts_in_ms"]
        second = None if countdown is None else (countdown + 999) // 1000
        return (
            tuple((player["name"], player["kind"])
                  for player in view["players"]),
            view["min_players"], view["max_players"], view["mode"], second,
            countdown is not None,
        )

    async def broadcast_lobby(self) -> None:
        view = self.lobby_view()
        self._last_lobby_signature = self._lobby_signature(view)
        recipients = list(self.lobby.waiting) + list(self.spectators)
        for participant in recipients:
            try:
                await self.send(participant, view)
            except Exception:
                if self.config.verbose:
                    traceback.print_exc()

    async def _lobby_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopped:
            try:
                await asyncio.sleep(0.05)
                if self.match is not None:
                    continue
                mode_name, _, required = self._mode_for_waiting()
                waiting = len(self.lobby.waiting)
                if waiting < required:
                    if self.lobby.deadline is not None:
                        self.lobby.deadline = None
                        await self.broadcast_lobby()
                    continue
                if waiting >= self.config.max_players:
                    self.lobby.deadline = None
                    await self._start_match()
                    continue
                if self.lobby.deadline is None:
                    self.lobby.deadline = loop.time() + (
                        self.config.lobby_wait_ms / 1000
                    )
                    await self.broadcast_lobby()
                    continue
                if loop.time() >= self.lobby.deadline:
                    self.lobby.deadline = None
                    await self._start_match()
                    continue
                signature = self._lobby_signature(self.lobby_view())
                if signature != self._last_lobby_signature:
                    await self.broadcast_lobby()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("lobby loop error")

    async def _start_match(self) -> None:
        if self.match is not None:
            return
        mode_name, next_cursor, required = self._mode_for_waiting()
        count = min(self.config.max_players, len(self.lobby.waiting))
        if count < required:
            return
        participants = self.lobby.take(count)
        if not participants:
            return
        try:
            seed = (self.config.seed + self.match_index
                    if self.config.seed is not None
                    else random.randrange(2**31))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            match_id = f"m-{stamp}-{secrets.token_hex(2)}"
            engine = Engine(
                self.config.rules(),
                [(participant.name, participant.kind)
                 for participant in participants],
                seed,
                match_id,
                max_missed_turns=self.config.max_missed_turns,
                mode=mode_name,
            )
            if self.config.no_logs:
                log = NullLog()
            else:
                log = MatchLog(
                    f"{self.config.log_dir}/match-{stamp}-{match_id[-4:]}.jsonl"
                )
        except Exception:
            self.lobby.waiting[0:0] = participants
            LOGGER.exception("could not create match")
            return

        for index, participant in enumerate(participants, start=1):
            participant.player_id = f"P{index}"
            participant.state = "playing"
        match = Match(
            engine, participants, self, self.config.tick_ms,
            self.config.min_turn_ms, log, self._on_match_end,
        )
        for participant in participants:
            participant.match = match
        self.match = match
        self.mode_cursor = next_cursor
        self.match_index += 1
        self._match_task = asyncio.create_task(match.run())
        self._match_task.add_done_callback(self._match_done)
        LOGGER.info(
            "Match %s started: mode=%s players=%s seed=%s",
            match_id, mode_name,
            ",".join(participant.name for participant in participants), seed,
        )
        # Let the match enqueue start/state before the emptied lobby snapshot.
        await asyncio.sleep(0)
        await self.broadcast_lobby()

    def _match_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            LOGGER.error("match task failed", exc_info=(
                type(error), error, error.__traceback__,
            ))

    async def _on_match_end(self, match: Match) -> None:
        if self.match is not match:
            return
        self.match = None
        for participant in match.participants:
            participant.state = "idle"
            participant.match = None
        match.log.close()
        LOGGER.info(
            "Match %s ended: reason=%s turns=%s",
            match.engine.match_id, match.engine.end_reason,
            match.engine.completed_turns,
        )
        await self.broadcast_lobby()

    async def send(self, participant, message: dict) -> None:
        if participant.transport == "tcp":
            await participant.tcp.send(message)
        elif participant.transport == "http":
            if not hasattr(participant, "current_views"):
                participant.current_views = {}
            participant.current_views[participant.player_id] = message
        else:
            raise ValueError(f"unknown transport: {participant.transport}")

    async def broadcast_spectators(self, message: dict) -> None:
        for spectator in list(self.spectators):
            try:
                await self.send(spectator, message)
            except Exception:
                if self.config.verbose:
                    traceback.print_exc()
                with suppress(asyncio.CancelledError, Exception):
                    await spectator.tcp.close()

    async def add_to_lobby(self, participant) -> None:
        if len(self.lobby.waiting) >= self.config.max_players:
            raise ServerFull("the lobby is full")
        participant.state = "lobby"
        participant.match = None
        self.lobby.add(participant)
        await self.broadcast_lobby()

    async def remove_participant(self, participant) -> None:
        active = (participant.state in ("lobby", "playing")
                  or participant.match is not None)
        changed = self.lobby.remove(participant)
        if participant.match is not None:
            await participant.match.forfeit(participant)
        participant.state = "idle"
        participant.match = None
        if changed or active:
            await self.broadcast_lobby()

    def unique_name(self, raw: str) -> str:
        used = {participant.name.casefold()
                for participant in self.lobby.waiting if participant.name}
        if self.match is not None:
            used.update(participant.name.casefold()
                        for participant in self.match.participants
                        if participant.name)
        used.update(participant.name.casefold()
                    for participant in self.spectators if participant.name)
        if raw.casefold() not in used:
            return raw
        suffix = 2
        while True:
            ending = f"-{suffix}"
            candidate = raw[:20 - len(ending)] + ending
            if candidate.casefold() not in used:
                return candidate
            suffix += 1

    def client_count(self) -> int:
        tcp_count = len(self.gateway.connections) if self.gateway else 0
        return tcp_count + len(getattr(self, "sessions", {}))
