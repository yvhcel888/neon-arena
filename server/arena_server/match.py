"""Authoritative turn-based match loop."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import time
import traceback

from arena_server.engine import ActionError
from arena_server.protocol import PROTOCOL


class Match:
    def __init__(self, engine, participants, server, tick_ms: int,
                 min_turn_ms: int, log, on_end):
        self.engine = engine
        self.participants = list(participants)
        self.detached: set = set()
        self.server = server
        self.tick_ms = tick_ms
        self.min_turn_ms = min_turn_ms
        self.log = log
        self.on_end = on_end

        self.pending: dict[str, dict] = {}
        self.ready = asyncio.Event()
        self.closed = True
        self.start_payloads: dict[str, dict] = {}
        self.current_views: dict[str, dict] = {}
        self.current_spectator_view: dict | None = None
        self.start_payload: dict | None = None
        self.last_events: list[dict] = []
        self._reply_by_ms: int | None = None
        self.deadline: float | None = None
        self._finishing = False

    def _delivery_participants(self):
        return (participant for participant in self.participants
                if participant not in self.detached)

    def detach(self, participant) -> bool:
        if participant not in self.participants or participant in self.detached:
            return False
        self.detached.add(participant)
        self.pending.pop(participant.player_id, None)
        return True

    def _make_start(self, player_id: str | None) -> dict:
        payload = deepcopy(self.engine.start_payload(player_id))
        payload.update({
            "type": "start",
            "protocol": PROTOCOL,
            "tick_ms": self.tick_ms,
            "min_turn_ms": self.min_turn_ms,
        })
        return payload

    def _make_state(self, player_id: str | None,
                    reply_by_ms: int | None = None) -> dict:
        payload = deepcopy(self.engine.state_payload(player_id))
        payload.update({
            "type": "state",
            "match_id": self.engine.match_id,
            "tick_ms": self.tick_ms,
            "reply_by_ms": (int(time.time() * 1000) + self.tick_ms
                            if reply_by_ms is None else reply_by_ms),
        })
        return payload

    def _refresh_current_views(self, turn: int | None = None,
                               events_turn: int | None = None) -> None:
        completed = self.engine.completed_turns
        if turn is None:
            turn = completed
        if events_turn is None:
            events_turn = completed
        for participant in self._delivery_participants():
            player_id = participant.player_id
            view = self._make_state(player_id, self._reply_by_ms)
            view["turn"] = turn
            view["events_turn"] = events_turn
            view["events"] = deepcopy(self.engine.last_events)
            self.current_views[player_id] = view
        spectator = self._make_state(None, self._reply_by_ms)
        spectator["turn"] = turn
        spectator["events_turn"] = events_turn
        spectator["events"] = deepcopy(self.engine.last_events)
        self.current_spectator_view = spectator

    async def _send_to_participants(self, message: dict) -> None:
        for participant in self._delivery_participants():
            try:
                await self.server.send(participant, deepcopy(message))
            except Exception:
                # The connection read loop owns disconnect cleanup and forfeit.
                if self.server.config.verbose:
                    traceback.print_exc()

    def close_log(self) -> None:
        try:
            self.log.close()
        except Exception:
            traceback.print_exc()

    async def _finish(self, end_payload: dict) -> None:
        if self._finishing:
            return
        self._finishing = True
        self.closed = True
        self.deadline = None
        try:
            await self._send_to_participants(end_payload)
            await self.server.broadcast_spectators(deepcopy(end_payload))
            try:
                self.log.write(deepcopy(end_payload))
            except Exception:
                traceback.print_exc()
            self.close_log()
        finally:
            await self.on_end(self)

    async def run(self) -> None:
        try:
            self.start_payload = self._make_start(None)
            self.log.write(deepcopy(self.start_payload))
            for participant in self._delivery_participants():
                start = self._make_start(participant.player_id)
                self.start_payloads[participant.player_id] = start
            for participant in self._delivery_participants():
                try:
                    await self.server.send(
                        participant,
                        deepcopy(self.start_payloads[participant.player_id]),
                    )
                except Exception:
                    if self.server.config.verbose:
                        traceback.print_exc()
            await self.server.broadcast_spectators(deepcopy(self.start_payload))

            while not self.engine.finished:
                self.pending = {}
                self.ready.clear()
                self.closed = False
                self._reply_by_ms = int(time.time() * 1000) + self.tick_ms
                loop = asyncio.get_running_loop()
                self.deadline = loop.time() + self.tick_ms / 1000

                for participant in self._delivery_participants():
                    state = self._make_state(participant.player_id,
                                             self._reply_by_ms)
                    self.current_views[participant.player_id] = state
                    try:
                        await self.server.send(participant, deepcopy(state))
                    except Exception:
                        if self.server.config.verbose:
                            traceback.print_exc()
                spectator_state = self._make_state(None, self._reply_by_ms)
                self.current_spectator_view = spectator_state
                await self.server.broadcast_spectators(deepcopy(spectator_state))

                while not self.engine.finished:
                    alive_ids = [
                        player.id for player in self.engine.players.values()
                        if player.alive
                    ]
                    if all(player_id in self.pending
                           for player_id in alive_ids):
                        break
                    remaining = self.deadline - loop.time()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(self.ready.wait(), remaining)
                    except asyncio.TimeoutError:
                        break
                    self.ready.clear()

                if self.engine.finished:
                    break

                alive_ids = [
                    player.id for player in self.engine.players.values()
                    if player.alive
                ]
                all_submitted = all(player_id in self.pending
                                    for player_id in alive_ids)
                if all_submitted and self.min_turn_ms > 0:
                    await asyncio.sleep(self.min_turn_ms / 1000)
                if self.engine.finished:
                    break

                self.closed = True
                self.deadline = None
                actions = {
                    player_id: deepcopy(self.pending[player_id])
                    for player_id in alive_ids if player_id in self.pending
                }
                events = self.engine.resolve(actions)
                self.last_events = deepcopy(events)
                self._refresh_current_views()
                self.log.write(deepcopy(self.current_spectator_view))

            self._refresh_current_views(
                turn=self.engine.turn, events_turn=self.engine.events_turn,
            )
            await self._finish(self.engine.end_payload())
        except asyncio.CancelledError:
            self.closed = True
            self.deadline = None
            self.close_log()
            raise
        except Exception:
            traceback.print_exc()
            self.deadline = None
            if not self._finishing:
                self._refresh_current_views()
                try:
                    await self._finish(self.engine.end_payload(reason="aborted"))
                except Exception:
                    traceback.print_exc()
            self.close_log()

    def submit(self, participant, turn, action) -> dict:
        if (participant not in self.participants
                or participant in self.detached):
            raise ActionError("not_in_match", "participant is not in this match")
        if self.closed or self.engine.finished:
            raise ActionError("turn_closed", "the turn is already closed")
        if (self.deadline is not None
                and asyncio.get_running_loop().time() >= self.deadline):
            raise ActionError("turn_closed", "the turn deadline has passed")
        if turn != self.engine.turn:
            raise ActionError(
                "stale_turn",
                f"turn {turn} is stale; current turn is {self.engine.turn}",
            )
        normalized = self.engine.validate_action(
            participant.player_id, action, turn,
        )
        self.pending[participant.player_id] = normalized
        alive_ids = [
            player.id for player in self.engine.players.values()
            if player.alive
        ]
        if all(player_id in self.pending for player_id in alive_ids):
            self.ready.set()
        return normalized

    async def forfeit(self, participant, reason: str = "forfeit") -> bool:
        if participant not in self.participants:
            return False
        changed = self.engine.forfeit(participant.player_id)
        if changed:
            self.last_events = deepcopy(self.engine.last_events)
            turn = self.engine.turn
            self._refresh_current_views(turn=turn, events_turn=turn)
            for recipient in self._delivery_participants():
                try:
                    await self.server.send(
                        recipient,
                        deepcopy(self.current_views[recipient.player_id]),
                    )
                except Exception:
                    # The connection read loop owns disconnect cleanup
                    # and forfeit.
                    if self.server.config.verbose:
                        traceback.print_exc()
            await self.server.broadcast_spectators(
                deepcopy(self.current_spectator_view),
            )
            try:
                self.log.write(deepcopy(self.current_spectator_view))
            except Exception:
                traceback.print_exc()
            self.ready.set()
        return changed

    def view_for(self, participant) -> dict:
        player_id = participant.player_id
        start = self.start_payloads.get(player_id)
        if start is None:
            start = self._make_start(player_id)
        state = self.current_views.get(player_id)
        if state is None:
            state = self._make_state(player_id, self._reply_by_ms)
        view = {
            key: deepcopy(start[key])
            for key in ("match_id", "seed", "turn_limit", "rules", "arena")
        }
        view.update(deepcopy(state))
        view["submitted"] = player_id in self.pending
        view["your_action"] = deepcopy(self.pending.get(player_id))
        return view

    def snapshot_for_spectator(self) -> tuple[dict, dict]:
        start = self.start_payload
        if start is None:
            start = self._make_start(None)
        state = self.current_spectator_view
        if state is None:
            state = self._make_state(None, self._reply_by_ms)
        start_copy = deepcopy(start)
        state_copy = deepcopy(state)
        start_copy.pop("you", None)
        state_copy.pop("you", None)
        return start_copy, state_copy
