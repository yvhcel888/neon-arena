"""Minimal asyncio HTTP/1.1 JSON API for human players."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
import logging
import re
import time
from urllib.parse import urlsplit

from arena_server.engine import ActionError
from arena_server.protocol import ServerFull, validate_name

LOGGER = logging.getLogger(__name__)

MAX_HEADER_BYTES = 16 * 1024
MAX_BODY_BYTES = 32 * 1024
STREAM_LIMIT_BYTES = max(MAX_HEADER_BYTES, MAX_BODY_BYTES) + 4
HEADER_SCAN_BYTES = STREAM_LIMIT_BYTES + 4 * 1024
READ_TIMEOUT_SECONDS = 10.0
API_PATHS = {
    "/api/v1/health", "/api/v1/rules", "/api/v1/sessions",
    "/api/v1/state", "/api/v1/actions",
}
HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

ACTION_STATUS_400 = {
    "invalid_json", "invalid_name", "invalid_action",
    "insufficient_energy", "wall", "out_of_bounds", "no_active_node",
    "full_hp", "shield_full",
}
ACTION_STATUS_409 = {
    "stale_turn", "turn_closed", "not_in_match", "not_alive",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 request: HttpRequest | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.request = request


@dataclass
class HttpRequest:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


class HttpApi:
    def __init__(self, server, config):
        self.server = server
        self.config = config
        self.port: int | None = None
        self._server: asyncio.AbstractServer | None = None
        self._handlers: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._stopping = False
        self._cors_origins = {
            origin.strip() for origin in config.cors_origin.split(",")
            if origin.strip()
        }

    async def start(self) -> int:
        if self._server is not None:
            return self.port
        self._stopping = False
        self._server = await asyncio.start_server(
            self._client_connected, self.config.host, self.config.api_port,
            limit=STREAM_LIMIT_BYTES,
        )
        sockets = self._server.sockets or []
        self.port = sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        self._stopping = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for writer in list(self._writers):
            writer.close()
        current = asyncio.current_task()
        handlers = [task for task in self._handlers if task is not current]
        for task in handlers:
            task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        for writer in list(self._writers):
            with suppress(asyncio.CancelledError, Exception):
                await writer.wait_closed()
        self._writers.clear()

    def _client_connected(self, reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter) -> None:
        if self._stopping:
            writer.close()
            return
        if len(self._handlers) >= self.config.max_clients:
            asyncio.create_task(self._reject_client(writer))
            return
        task = asyncio.create_task(self._handle_client(reader, writer))
        self._handlers.add(task)
        self._writers.add(writer)
        task.add_done_callback(self._handlers.discard)

    async def _reject_client(self, writer: asyncio.StreamWriter) -> None:
        try:
            if not self._stopping:
                await self._write_response(
                    writer, 503,
                    self._error("server_full", "the server is full"),
                )
                # Closing with unread request bytes resets Windows sockets
                # and can discard the rejection before the peer receives it.
                await asyncio.sleep(0)
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, Exception):
                await writer.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        request = None
        try:
            try:
                request = await asyncio.wait_for(
                    self._read_request(reader), READ_TIMEOUT_SECONDS,
                )
                status, payload = await self._dispatch(request)
            except ApiError as exc:
                if exc.request is not None:
                    request = exc.request
                status, payload = exc.status, self._error(exc.code, exc.message)
            except ActionError as exc:
                status = self._action_status(exc.code)
                if status is None:
                    LOGGER.exception("unmapped action error")
                    status, payload = 500, self._error(
                        "internal_error", "the server could not process the request",
                    )
                else:
                    payload = self._error(exc.code, exc.message)
            except ServerFull:
                status, payload = 503, self._error(
                    "server_full", "the server or lobby is full",
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                status, payload = 408, self._error(
                    "request_timeout", "the request timed out",
                )
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                status, payload = 400, self._error(
                    "invalid_request", "the request was incomplete",
                )
            except Exception:
                LOGGER.exception("HTTP request failed")
                status, payload = 500, self._error(
                    "internal_error", "the server could not process the request",
                )
            if not self._stopping:
                await self._write_response(writer, status, payload, request)
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()
            with suppress(asyncio.CancelledError, Exception):
                await writer.wait_closed()

    @staticmethod
    def _request_metadata(raw_headers: bytes) -> HttpRequest:
        headers: dict[str, str] = {}
        try:
            lines = raw_headers.decode("iso-8859-1").split("\r\n")
        except UnicodeError:
            return HttpRequest("", "", headers, b"")
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if not separator or HEADER_NAME.fullmatch(name) is None:
                continue
            key = name.lower()
            if key not in headers:
                headers[key] = value.strip()
        return HttpRequest("", "", headers, b"")

    async def _read_request(self, reader: asyncio.StreamReader) -> HttpRequest:
        try:
            raw_headers = await reader.readuntil(b"\r\n\r\n")
        except asyncio.LimitOverrunError as exc:
            partial = await reader.read(HEADER_SCAN_BYTES)
            request = self._request_metadata(partial)
            raise ApiError(431, "headers_too_large",
                           "request headers exceed 16 KiB",
                           request=request) from exc
        except asyncio.IncompleteReadError as exc:
            request = self._request_metadata(exc.partial)
            raise ApiError(400, "invalid_request",
                           "the request was incomplete",
                           request=request) from exc
        request = self._request_metadata(raw_headers)
        if len(raw_headers) > MAX_HEADER_BYTES:
            raise ApiError(431, "headers_too_large",
                           "request headers exceed 16 KiB",
                           request=request)
        try:
            text = raw_headers.decode("iso-8859-1")
            lines = text[:-4].split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            if version != "HTTP/1.1" or not target:
                raise ValueError
            headers: dict[str, str] = {}
            for line in lines[1:]:
                name, separator, value = line.partition(":")
                if not separator or HEADER_NAME.fullmatch(name) is None:
                    raise ValueError
                key = name.lower()
                if key in headers:
                    raise ValueError
                if any(ord(char) < 32 and char != "\t" for char in value):
                    raise ValueError
                headers[key] = value.strip()
        except (UnicodeError, ValueError) as exc:
            raise ApiError(400, "invalid_request",
                           "malformed HTTP request",
                           request=request) from exc
        request = HttpRequest(method, target, headers, b"")

        if "transfer-encoding" in headers:
            raise ApiError(400, "unsupported_transfer_encoding",
                           "chunked request bodies are not supported",
                           request=request)
        content_length = 0
        if "content-length" in headers:
            raw_length = headers["content-length"]
            if not raw_length.isascii() or not raw_length.isdigit():
                raise ApiError(400, "invalid_content_length",
                               "Content-Length must be a non-negative integer",
                               request=request)
            normalized = raw_length.lstrip("0") or "0"
            maximum = str(MAX_BODY_BYTES)
            if (len(normalized) > len(maximum)
                    or (len(normalized) == len(maximum)
                        and normalized > maximum)):
                raise ApiError(413, "body_too_large",
                               "request body exceeds 32 KiB",
                               request=request)
            content_length = int(normalized)
        try:
            request.body = (await reader.readexactly(content_length)
                            if content_length else b"")
        except asyncio.IncompleteReadError as exc:
            raise ApiError(400, "invalid_request",
                           "the request was incomplete",
                           request=request) from exc
        return request

    async def _dispatch(self, request: HttpRequest) -> tuple[int, dict]:
        if request.method == "OPTIONS":
            return 204, {}

        try:
            parsed = urlsplit(request.target)
        except ValueError as exc:
            raise ApiError(400, "invalid_request",
                           "malformed request target") from exc
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
            raise ApiError(400, "invalid_request",
                           "request target must be an origin-form path")
        path = parsed.path
        if path not in API_PATHS:
            if path.startswith("/api/v1/"):
                raise ApiError(404, "not_found",
                               "API endpoint was not found")
            raise ApiError(404, "not_found", "path was not found")

        if request.method == "GET" and path == "/api/v1/health":
            return 200, self.server.health_payload()
        if request.method == "GET" and path == "/api/v1/rules":
            return 200, self.server.rules_payload()
        if request.method == "POST" and path == "/api/v1/sessions":
            return 200, await self._create_or_recover(request)
        if request.method == "GET" and path == "/api/v1/state":
            session = self._require_session(request)
            return 200, {"ok": True, "view": self.server.view_for(
                session.participant,
            )}
        if request.method == "POST" and path == "/api/v1/actions":
            session = self._require_session(request)
            return 200, self._submit_action(session, request.body)
        if request.method == "DELETE" and path == "/api/v1/sessions":
            session = self._require_session(request)
            participant = session.participant
            try:
                await self.server.remove_participant(participant)
            finally:
                self.server.sessions.drop(session.token)
                participant.session = None
            return 200, {"ok": True}
        raise ApiError(405, "method_not_allowed", "method is not supported")

    def _body_object(self, body: bytes) -> dict:
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ApiError(400, "invalid_json", "body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "invalid_json", "JSON body must be an object")
        return payload

    async def _create_or_recover(self, request: HttpRequest) -> dict:
        token = self._bearer_token(request.headers.get("authorization"))
        session = self.server.sessions.get(token)
        if session is not None:
            self._record_request(session)
            participant = session.participant
            if participant.state in ("lobby", "playing"):
                view = self.server.view_for(participant)
            elif participant.state == "idle":
                view = await self.server.requeue(participant)
            else:
                raise RuntimeError(f"unknown participant state: {participant.state}")
            return {"ok": True, "token": session.token, "view": view}
        payload = self._body_object(request.body)
        if token is not None and "name" not in payload:
            raise ApiError(401, "unauthorized", "a valid bearer token is required")
        try:
            name = validate_name(payload.get("name"))
        except ValueError as exc:
            raise ApiError(400, "invalid_name", str(exc)) from exc
        session, participant = await self.server.create_human(name)
        return {
            "ok": True, "token": session.token,
            "view": self.server.view_for(participant),
        }

    def _submit_action(self, session, body: bytes) -> dict:
        payload = self._body_object(body)
        turn = payload.get("turn")
        if not isinstance(turn, int) or isinstance(turn, bool):
            raise ApiError(400, "invalid_action", "turn must be an integer")
        participant = session.participant
        match = participant.match
        if participant.state != "playing" or match is None:
            raise ActionError("not_in_match", "participant is not in a match")
        normalized = match.submit(participant, turn, payload.get("action"))
        return {"ok": True, "turn": turn, "action": normalized}

    @staticmethod
    def _bearer_token(header: str | None) -> str | None:
        if header is None:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1]:
            return "invalid"
        return parts[1]

    def _require_session(self, request: HttpRequest):
        token = self._bearer_token(request.headers.get("authorization"))
        session = self.server.sessions.get(token)
        if session is None:
            raise ApiError(401, "unauthorized", "a valid bearer token is required")
        self._record_request(session)
        return session

    def _record_request(self, session) -> None:
        now = time.monotonic()
        session.last_poll = now
        if not self.server.sessions.allow_request(session, now):
            raise ApiError(429, "rate_limited", "session request rate limit exceeded")

    @staticmethod
    def _action_status(code: str) -> int | None:
        if code in ACTION_STATUS_400:
            return 400
        if code in ACTION_STATUS_409:
            return 409
        if code == "server_full":
            return 503
        return None

    @staticmethod
    def _error(code: str, message: str) -> dict:
        return {"ok": False, "error": {"code": code, "message": message}}

    def _cors_headers(self, request: HttpRequest | None) -> dict[str, str]:
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
        }
        if self.config.cors_origin == "*":
            headers["Access-Control-Allow-Origin"] = "*"
        else:
            origin = request.headers.get("origin") if request is not None else None
            if origin in self._cors_origins:
                headers["Access-Control-Allow-Origin"] = origin
        return headers

    async def _write_response(self, writer: asyncio.StreamWriter,
                              status: int, payload: dict,
                              request: HttpRequest | None = None) -> None:
        reason = {
            200: "OK", 204: "No Content", 400: "Bad Request",
            401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed",
            408: "Request Timeout", 409: "Conflict", 413: "Payload Too Large",
            429: "Too Many Requests", 431: "Request Header Fields Too Large",
            500: "Internal Server Error", 503: "Service Unavailable",
        }.get(status, "Error")
        try:
            body = b"" if status == 204 else (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                .encode("utf-8")
            )
        except Exception:
            LOGGER.exception("HTTP response serialization failed")
            status = 500
            reason = "Internal Server Error"
            payload = self._error(
                "internal_error", "the server could not process the request",
            )
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
            "Connection": "close",
            **self._cors_headers(request),
        }
        head = f"HTTP/1.1 {status} {reason}\r\n" + "".join(
            f"{key}: {value}\r\n" for key, value in headers.items()
        ) + "\r\n"
        writer.write(head.encode("ascii") + body)
        await writer.drain()


__all__ = ["HttpApi"]
