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
        return any(p.score >= self.state["target_score"]
                   for p in self.engine.players.values())


class SurvivalMode(GameMode):
    SHRINK_TURNS = (6, 12, 18, 24, 30)

    def setup(self):
        return {"zone": {"min": [1, 1], "max": [13, 13]},
                "next_shrink_turn": 6,
                "storm_damage": 12}

    def _in_storm(self, pos):
        x, y = pos
        zone = self.state["zone"]
        return not (zone["min"][0] <= x <= zone["max"][0]
                    and zone["min"][1] <= y <= zone["max"][1])

    def player_fields(self, player):
        return {"in_storm": self._in_storm(player.pos)}

    def after_deaths(self, events):
        turn = self.engine.turn
        if turn not in self.SHRINK_TURNS:
            return
        zone = {"min": [min(self.state["zone"]["min"][0] + 1, 6)] * 2,
                "max": [max(self.state["zone"]["max"][0] - 1, 8)] * 2}
        next_shrink_turn = turn + 6 if turn < 30 else None
        self.state["zone"] = zone
        self.state["next_shrink_turn"] = next_shrink_turn
        events.append({"type": "storm_shrink", "zone": zone,
                       "next_shrink_turn": next_shrink_turn})

        damage = self.state["storm_damage"]
        for player in self.engine.players.values():
            if not player.alive or not self._in_storm(player.pos):
                continue
            player.hp = max(0, player.hp - damage)
            events.append({"type": "storm_damage", "player": player.id,
                           "amount": damage, "hp": player.hp})
            if player.hp == 0:
                player.alive = False
                events.append({"type": "death", "player": player.id,
                               "killer": None})


class TeamMode(GameMode):
    def setup(self):
        if len(self.engine.players) != 4:
            raise ValueError("team mode requires exactly 4 players")
        return {
            "teams": [
                {"id": "T1", "name": "Team A", "members": ["P1", "P2"],
                 "score": 0, "alive": 2},
                {"id": "T2", "name": "Team B", "members": ["P3", "P4"],
                 "score": 0, "alive": 2},
            ],
        }

    def _team_for(self, player_id):
        for team in self.state["teams"]:
            if player_id in team["members"]:
                return team
        return None

    def player_fields(self, player):
        team = self._team_for(player.id)
        return {"team": team["id"] if team is not None else ""}

    def friendly(self, attacker_id, target_id):
        attacker_team = self._team_for(attacker_id)
        target_team = self._team_for(target_id)
        return (attacker_team is not None and target_team is not None
                and attacker_team["id"] == target_team["id"])

    def _refresh_teams(self):
        for team in self.state["teams"]:
            members = [self.engine.players[player_id]
                       for player_id in team["members"]]
            team["score"] = sum(player.score for player in members)
            team["alive"] = sum(player.alive for player in members)

    def after_missed(self, events):
        self._refresh_teams()

    def on_forfeit(self, player_id, events):
        self._refresh_teams()

    def alive_unit_count(self):
        self._refresh_teams()
        return sum(team["alive"] > 0 for team in self.state["teams"])

    def _ranked_teams(self):
        self._refresh_teams()
        rows = []
        for team in self.state["teams"]:
            members = [self.engine.players[player_id]
                       for player_id in team["members"]]
            rows.append({
                **team,
                "members": list(team["members"]),
                "hp": sum(player.hp for player in members),
                "energy": sum(player.energy for player in members),
            })
        return sorted(rows, key=lambda team: (
            -team["alive"], -team["score"], -team["hp"],
            -team["energy"], team["id"],
        ))

    def winner(self, standings):
        teams = self._ranked_teams()
        if not teams:
            return None
        team = teams[0]
        return {"id": team["id"], "name": team["name"], "kind": "team",
                "members": list(team["members"])}

    def end_extras(self):
        return {"team_standings": self._ranked_teams()}


def create_game_mode(engine, name):
    classes = {"classic": ClassicMode, "king": KingMode,
               "survival": SurvivalMode, "team": TeamMode}
    if name not in classes:
        raise ValueError(f"unknown mode: {name}")
    mode = classes[name]()
    mode.engine = engine
    mode.state = mode.setup()
    return mode
