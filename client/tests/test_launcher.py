import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest


CLIENT = Path(__file__).resolve().parents[1]
LAUNCHER = CLIENT / "launcher.py"
ASSETS = {"/": "index.html", "/style.css": "style.css", "/app.js": "app.js"}


def unused_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RunningLauncher:
    def __init__(self, port=None):
        self.port = port or unused_port()
        self.process = None

    def __enter__(self):
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(LAUNCHER),
                "--host", "127.0.0.1",
                "--port", str(self.port),
                "--no-open",
            ],
            cwd=str(CLIENT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        try:
            self._wait_until_ready()
        except BaseException:
            self.stop()
            raise
        return self

    def _wait_until_ready(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output, _ = self.process.communicate(timeout=1)
                raise AssertionError(
                    "launcher exited before becoming ready:\n" + output
                )
            try:
                status, _, _ = self.request("GET", "/")
                if status == 200:
                    return
            except (ConnectionError, OSError, http.client.HTTPException):
                pass
            time.sleep(0.05)
        raise AssertionError("launcher did not become ready within 10 seconds")

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def stop(self):
        if self.process is None:
            return ""
        if self.process.poll() is None:
            self.process.terminate()
        try:
            output, _ = self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            output, _ = self.process.communicate(timeout=5)
        return output

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()


class LauncherRuntimeTests(unittest.TestCase):
    def test_get_and_head_serve_only_the_three_public_routes(self):
        with RunningLauncher() as launcher:
            for route, filename in ASSETS.items():
                with self.subTest(route=route):
                    expected = (CLIENT / filename).read_bytes()
                    status, headers, body = launcher.request("GET", route)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, expected)
                    self.assertEqual(headers.get("Cache-Control"), "no-store")

                    status, headers, body = launcher.request("HEAD", route)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, b"")
                    self.assertEqual(headers.get("Content-Length"), str(len(expected)))

    def test_private_traversal_and_api_paths_are_not_served(self):
        blocked_paths = (
            "/index.html",
            "/README.md",
            "/launcher.py",
            "/tests/test_static.py",
            "/tests/",
            "/missing",
            "/../README.md",
            "/%2e%2e/README.md",
            "/%2E%2E%2FREADME.md",
            "/..%5CREADME.md",
            "/%2e%2e%5cREADME.md",
            "/%2fstyle.css",
            "http://example.invalid/style.css",
            "/api/v1/health",
            "/api/v1/sessions",
        )
        with RunningLauncher() as launcher:
            for path in blocked_paths:
                with self.subTest(path=path):
                    status, _, body = launcher.request("GET", path)
                    self.assertEqual(status, 404)
                    self.assertNotIn(b"NEON ARENA", body)

    def test_post_is_not_supported(self):
        with RunningLauncher() as launcher:
            status, _, body = launcher.request(
                "POST", "/api/v1/sessions", body=b"{}",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 501)
            self.assertIn(b"POST", body)

    def test_occupied_port_exits_nonzero_with_clear_error(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            result = subprocess.run(
                [
                    sys.executable,
                    str(LAUNCHER),
                    "--host", "127.0.0.1",
                    "--port", str(port),
                    "--no-open",
                ],
                cwd=str(CLIENT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("launcher error:", output)
        self.assertIn(f"cannot bind 127.0.0.1:{port}", output)

    def test_process_cleanup_waits_for_launcher_exit(self):
        launcher = RunningLauncher()
        with launcher:
            self.assertIsNone(launcher.process.poll())
        self.assertIsNotNone(launcher.process.returncode)


if __name__ == "__main__":
    unittest.main()
