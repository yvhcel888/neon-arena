MODE_ORDER = ("classic", "king", "team", "survival", "bounty")
MODE_MIN_PLAYERS = {"classic": 2, "king": 2, "team": 4,
                    "survival": 2, "bounty": 2}
MODE_LABELS = {"classic": "Classic", "king": "King of the Hill",
               "team": "Team 2v2", "survival": "Survival",
               "bounty": "Bounty"}
MODE_DESCRIPTIONS = {
    "classic": "Last player standing or highest score.",
    "king": "Hold the center zone to build score.",
    "team": "Two teams of two; friendly fire is disabled.",
    "survival": "Stay inside the shrinking safe zone.",
    "bounty": "Hunt your assigned target for bonus score.",
}


def select_mode(requested: str, waiting_count: int, cursor: int) -> tuple[str, int]:
    if requested not in (*MODE_ORDER, "rotation"):
        raise ValueError(f"unknown mode: {requested}")
    if requested != "rotation":
        return requested, cursor
    for offset in range(len(MODE_ORDER)):
        index = (cursor + offset) % len(MODE_ORDER)
        name = MODE_ORDER[index]
        if waiting_count >= MODE_MIN_PLAYERS[name]:
            return name, (index + 1) % len(MODE_ORDER)
    return "classic", (cursor + 1) % len(MODE_ORDER)


class GameMode:
    def setup(self):
        return {}

    def player_fields(self, player):
        return {}

    def friendly(self, attacker_id, target_id):
        return False

    def damage_multiplier(self, attacker, target):
        return 1

    def kill_reward(self, attacker, target):
        return self.engine.rules.kill_score

    def after_deaths(self, events):
        return None

    def after_missed(self, events):
        return None

    def on_forfeit(self, player_id, events):
        return None

    def alive_unit_count(self):
        return sum(p.alive for p in self.engine.players.values())

    def score_limit_reached(self):
        return False

    def winner(self, standings):
        if not standings:
            return None
        row = standings[0]
        return {"id": row["id"], "name": row["name"]}

    def end_extras(self):
        return {}


class ClassicMode(GameMode):
    pass


class KingMode(GameMode):
    def setup(self):
        return {"zone": {"min": [6, 6], "max": [8, 8]},
                "target_score": 100,
                "streaks": {pid: 0 for pid in self.engine.players}}

    def player_fields(self, player):
        return {"hill_streak": self.state["streaks"][player.id]}

    def on_forfeit(self, player_id, events):
        self.state["streaks"][player_id] = 0

    def after_missed(self, events):
        for player in self.engine.players.values():
            if not player.alive:
                self.state["streaks"][player.id] = 0
                continue
            x, y = player.pos
            if 6 <= x <= 8 and 6 <= y <= 8:
                previous = self.state["streaks"][player.id]
                points = 5 + min(previous, 5)
                player.score += points
                streak = previous + 1
                self.state["streaks"][player.id] = streak
                events.append({"type": "hill_score", "player": player.id,
                               "pos": [x, y], "points": points,
                               "streak": streak, "score": player.score})
            else:
                self.state["streaks"][player.id] = 0

    def score_limit_reached(self):
        return any(p.alive and p.score >= self.state["target_score"]
                   for p in self.engine.players.values())


def create_game_mode(engine, name):
    classes = {"classic": ClassicMode, "king": KingMode}
    if name not in classes:
        raise ValueError(f"unknown mode: {name}")
    mode = classes[name]()
    mode.engine = engine
    mode.state = mode.setup()
    return mode
