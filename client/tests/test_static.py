import ast
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]


def source(name):
    path = CLIENT / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


class ScreenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = []
        self.ids = set()
        self.button_types = []
        self.scripts = []
        self.stylesheets = []
        self.lang = None
        self.live_regions = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if tag == "html":
            self.lang = values.get("lang")
        if tag == "section" and "screen" in values.get("class", "").split():
            self.sections.append(values.get("id"))
        if tag == "button":
            self.button_types.append(values.get("type"))
        if tag == "script" and "src" in values:
            self.scripts.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values.get("href"))
        if values.get("aria-live") == "polite":
            self.live_regions += 1


class StaticTests(unittest.TestCase):
    def test_required_files(self):
        for name in ("index.html", "style.css", "app.js", "launcher.py", "README.md"):
            self.assertTrue((CLIENT / name).is_file(), name)

    def test_no_external_runtime_dependencies(self):
        text = "\n".join(source(name) for name in
                         ("index.html", "style.css", "app.js"))
        for bad in ("cdn.", "unpkg.com", "jsdelivr", "googleapis",
                    "<script src=\"http", "<link href=\"http"):
            self.assertNotIn(bad, text)

    def test_no_inner_html_with_user_data(self):
        app = source("app.js")
        self.assertNotIn("innerHTML", app)
        self.assertNotIn("outerHTML", app)
        self.assertNotIn("insertAdjacentHTML", app)
        self.assertIn("textContent", app)

    def test_server_address_is_configurable(self):
        app = source("app.js")
        for token in ("neon.server", "neon.token.", "/api/v1", "Authorization",
                      "Bearer "):
            self.assertIn(token, app)
        for method in ("health()", "createSession(", "recover(", "state(",
                       "action(", "leave("):
            self.assertIn(method, app)

    def test_four_screens_local_assets_and_accessibility(self):
        parser = ScreenParser()
        parser.feed(source("index.html"))
        self.assertEqual(parser.lang, "zh-CN")
        self.assertEqual(parser.sections, [
            "screen-connect", "screen-lobby", "screen-game", "screen-result",
        ])
        self.assertEqual(parser.scripts, ["app.js"])
        self.assertEqual(parser.stylesheets, ["style.css"])
        self.assertGreaterEqual(parser.live_regions, 1)
        self.assertTrue(parser.button_types)
        self.assertTrue(all(kind == "button" for kind in parser.button_types))
        for element_id in (
            "server", "name", "connect", "health-status", "connect-error",
            "lobby-players", "lobby-count", "lobby-countdown", "lobby-mode",
            "lobby-mode-description", "lobby-rules", "leave-lobby", "board",
            "turn", "countdown", "countdown-progress", "mode-badge",
            "hud-self", "hud-players", "event-log", "game-status",
            "action-move", "action-dash", "action-attack", "action-gather",
            "action-shield", "action-heal", "action-wait", "dpad",
            "result-winner", "result-reason", "result-standings",
            "result-team-standings", "result-stats", "again", "leave-result",
        ):
            self.assertIn(element_id, parser.ids)

    def test_canvas_and_interaction_contract(self):
        app = source("app.js")
        for token in (
            "devicePixelRatio", "requestAnimationFrame", "drawBoard",
            "renderHud", "renderLobby", "renderGame", "renderResult",
            "formatEvent", "reply_by_ms", "clockOffset", "submitted",
            "keydown", "pointerdown", "selectedAction", "pollInFlight",
            "pollTimer", "backoff", "setTimeout", "visibilitychange",
            "stale_turn", "turn_closed", "unauthorized",
        ):
            self.assertIn(token, app)
        for direction in ('"n"', '"e"', '"s"', '"w"'):
            self.assertIn(direction, app)
        for action in ("move", "dash", "attack", "gather", "shield", "heal", "wait"):
            self.assertIn(action, app)

    def test_mode_rendering_hooks_exist(self):
        app = source("app.js")
        for token in ("mode_state", "hill_streak", "in_storm",
                      "bounty_target", "team_standings", "score_limit"):
            self.assertIn(token, app)
        self.assertIn("textContent", app)
        self.assertNotIn("innerHTML", app)

    def test_all_mode_visual_branches_exist(self):
        app = source("app.js")
        for token in (
            'case "classic"', 'case "king"', 'case "survival"',
            'case "team"', 'case "bounty"', "mode_state.zone",
            "next_shrink_turn", "bounty_streak", "teamFor",
        ):
            self.assertIn(token, app)
        for token in ("mode_label", "mode_description", "winner.kind",
                      "kind === \"team\"", "达到目标分数"):
            self.assertIn(token, app)

    def test_neon_responsive_and_reduced_motion_styles(self):
        css = source("style.css")
        for token in ("#070b14", "aspect-ratio: 1", "@media (max-width: 860px)",
                      "prefers-reduced-motion: reduce", "--progress", "#2de2e6",
                      "#ff4fd8", "#8dff57", "#ffc857"):
            self.assertIn(token, css)

    def test_launcher_is_stdlib_only_and_read_only(self):
        text = source("launcher.py")
        self.assertTrue(text)
        tree = ast.parse(text)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        external = sorted(imported - set(sys.stdlib_module_names))
        self.assertEqual(external, [])
        for token in ("SimpleHTTPRequestHandler", "do_GET", "do_HEAD",
                      "--host", "--port", "--server", "--no-open", "urlencode",
                      "allow_reuse_address = False"):
            self.assertIn(token, text)
        for forbidden in ("do_POST", "do_PUT", "do_DELETE", "translate_path"):
            self.assertNotIn(forbidden, text)

    def test_readme_documents_launcher_and_security_boundary(self):
        readme = source("README.md")
        for token in ("python launcher.py", "--server", "--no-open",
                      "neon.server", "neon.token.", "textContent", "API"):
            self.assertIn(token, readme)


if __name__ == "__main__":
    unittest.main()
