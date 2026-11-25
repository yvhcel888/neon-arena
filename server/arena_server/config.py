from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    max_hp: int = 100
    max_energy: int = 100
    start_energy: int = 40
    energy_regen: int = 4
    attack_cost: int = 8
    attack_damage: int = 22
    dash_cost: int = 18
    dash_distance: int = 2
    heal_cost: int = 25
    heal_amount: int = 25
    shield_cost: int = 12
    shield_amount: int = 26
    max_shield: int = 40
    gather_energy: int = 30
    gather_score: int = 10
    node_cooldown: int = 4
    damage_score: int = 1
    kill_score: int = 25
    turn_limit: int = 80

    def to_dict(self) -> dict:
        return {
            "max_hp": self.max_hp, "max_energy": self.max_energy,
            "start_energy": self.start_energy, "energy_regen": self.energy_regen,
            "attack": {"cost": self.attack_cost, "damage": self.attack_damage},
            "dash": {"cost": self.dash_cost, "distance": self.dash_distance},
            "heal": {"cost": self.heal_cost, "amount": self.heal_amount},
            "shield": {"cost": self.shield_cost, "amount": self.shield_amount,
                       "max": self.max_shield},
            "gather": {"energy": self.gather_energy,
                       "node_cooldown": self.node_cooldown},
            "score": {"damage": self.damage_score, "kill": self.kill_score,
                      "gather": self.gather_score},
            "turn_limit": self.turn_limit,
        }


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    tcp_port: int = 7777
    api_port: int = 8080
    tick_ms: int = 15000
    min_turn_ms: int = 250
    turn_limit: int = 80
    min_players: int = 2
    max_players: int = 4
    lobby_wait_ms: int = 5000
    max_missed_turns: int = 4
    seed: int | None = None
    log_dir: str = "logs"
    no_logs: bool = False
    cors_origin: str = "*"
    max_clients: int = 32
    verbose: bool = False
    mode: str = "rotation"

    def rules(self) -> Rules:
        return Rules(turn_limit=self.turn_limit)
