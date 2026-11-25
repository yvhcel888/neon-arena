#!/usr/bin/env python3
"""Confined standard-library static server for the NEON ARENA web client."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, HTTPServer
import mimetypes
from pathlib import Path
import socketserver
import sys
from urllib.parse import unquote, urlencode, urlsplit
import webbrowser

CLIENT_DIR = Path(__file__).resolve().parent
ASSETS = {"/": "index.html", "/style.css": "style.css", "/app.js": "app.js"}


class NeonRequestHandler(SimpleHTTPRequestHandler):
    """Serve only three client assets; never proxy or mutate game state."""

    server_version = "NeonArenaStatic/1.0"
    sys_version = ""

    def _asset(self) -> Path | None:
        try:
            target = urlsplit(self.path)
            raw_path = unquote(target.path, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None
        if target.scheme or target.netloc or target.fragment or "\x00" in raw_path:
            return None
        relative = ASSETS.get(raw_path)
        if relative is None:
            return None
        candidate = (CLIENT_DIR / relative).resolve(strict=False)
        try:
            candidate.relative_to(CLIENT_DIR)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _serve(self, include_body: bool) -> None:
        asset = self._asset()
        if asset is None:
            self.send_error(404, "Not Found")
            return
        try:
            data = asset.read_bytes()
        except OSError:
            self.send_error(404, "Not Found")
            return
        content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src http: https:; img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def do_GET(self) -> None:
        self._serve(include_body=True)

    def do_HEAD(self) -> None:
        self._serve(include_body=False)

    def log_message(self, format: str, *args) -> None:
        return


class ThreadingNeonServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python launcher.py",
        description="Serve the standalone NEON ARENA client on loopback.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8090, help="listen port (default: 8090)")
    parser.add_argument("--server", help="preset game API server in the opened URL")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    return parser


def open_url(host: str, port: int, server: str | None) -> str:
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    url = f"http://{display_host}:{port}/"
    if server:
        url += "?" + urlencode({"server": server})
    return url


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handler = partial(NeonRequestHandler, directory=str(CLIENT_DIR))
    try:
        server = ThreadingNeonServer((args.host, args.port), handler)
    except OSError as exc:
        print(
            f"launcher error: cannot bind {args.host}:{args.port}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    actual_port = server.server_address[1]
    url = open_url(args.host, actual_port, args.server)
    print(f"NEON ARENA client: {url}", flush=True)
    print(f"Serving only {CLIENT_DIR}; press Ctrl+C to stop.", flush=True)
    if not args.no_open:
        try:
            webbrowser.open(url)
        except webbrowser.Error as exc:
            print(f"browser warning: {exc}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
