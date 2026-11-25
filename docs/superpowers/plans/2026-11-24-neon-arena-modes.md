# NEON ARENA 多模式完成计划 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 NEON ARENA 可运行基线，并加入经典、据点、2v2 团队、生存缩圈、赏金五种模式与自动轮换，支持人类和 Agent 任意混搭。

**Architecture:** Python 标准库权威服务端使用共享 `Engine` 与独立 `modes.py` 模式层；TCP NDJSON 与 HTTP JSON 只通过协议通信；独立 Python Agent SDK 与原生 Web 客户端消费服务端下发的模式状态，不在本地计算规则结果。

**Tech Stack:** Python 3.10+（asyncio、unittest、http.server）、原生 HTML/CSS/JS Canvas、PowerShell 5.1、Git；零第三方运行依赖。

**Design:** `docs/superpowers/specs/2026-11-24-neon-arena-modes-design.md`

**Baseline plan:** `docs/superpowers/plans/2026-11-23-neon-arena.md`。Task 6–11 必须同时执行基线计划中对应的 Task 4–9；本计划只写模式增量与最终组合要求，基线任务brief 是那些任务不可分割的组成部分。

## Global Constraints

- Python 最低 3.10，禁止第三方运行依赖；服务端/Agent 只用标准库；客户端无 CDN、无构建工具。
- 三个独立目录：`server/`、`agents/`、`client/`；服务端不导入 Agent/客户端代码，不返回 HTML/JS/CSS。
- 服务端端口：TCP Agent `7777`、HTTP API `8080`；客户端本地 launcher `8090`。均可配置。
- 客户端只是 HTTP API 消费者；游戏规则、校验、结算、模式效果只在服务端。
- 所有网络字段遵循基线规格 §5、§6 与模式设计 §11；坐标 `[x,y]`，方向 `n/e/s/w`。
- 人类与 Agent 混用同一大厅/对局；每局 2–4 人，单活动对局，其余排队；团队模式固定 4 人。
- 默认 `mode="rotation"`，轮换顺序 `classic -> king -> team -> survival -> bounty`；人数不足时跳过不可玩模式。
- 现有七种动作、能量经济和经典模式规则保持不变；TCP 协议版本保持 `1`，只追加字段。
- 五种模式全部为严格回合制：完整状态广播、统一决策窗口、同时结算；没有实时移动、瞄准或持续攻击。LLM 对局通过提高 `--tick-ms` 获得思考时间，截止后动作不追溯生效。
- 测试框架使用 `unittest`；每个 Task 独立提交 Git；不生成占位功能。
- 编码 UTF-8；Windows 主路径，兼容 Linux/macOS；日志/控制台为 ASCII 或 UTF-8。
- 所有动态 Web 文本使用 `textContent`，禁止用 `innerHTML` 拼接用户数据。
- 每个实现 Task 必须提供 TDD RED/GREEN 证据、真实测试结果与自审报告。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `server/arena_server/modes.py` | 模式元数据、轮换选择、五种模式权威逻辑与扩展事件 |
| `server/arena_server/engine.py` | 共享动作、移动、资源、战斗、死亡、漏操作、序列化与模式钩子 |
| `server/arena_server/config.py` | `Rules`、`ServerConfig.mode`、CLI 参数 |
| `server/arena_server/protocol.py` | 协议版本、错误码、消息辅助 |
| `server/arena_server/participants.py` | 统一 TCP/HTTP 参与者 |
| `server/arena_server/lobby.py` | 排队、模式感知倒计时、开局 |
| `server/arena_server/match.py` | 单局循环、动作收集、计时、结束、日志 |
| `server/arena_server/tcp_gateway.py` | TCP NDJSON、路由、观战 |
| `server/arena_server/http_api.py` | HTTP/JSON、CORS、轮询视图 |
| `server/arena_server/sessions.py` | HTTP session/token/清理 |
| `server/arena_server/logging_utils.py` | JSONL 对局日志 |
| `server/arena_server/server.py` | 组装、生命周期、轮换、混合视图 |
| `server/arena_server/__main__.py` | `python -m arena_server` |
| `server/tests/test_modes.py` | 五种模式引擎测试 |
| `server/tests/test_rotation.py` | 轮换与人数跳过测试 |
| `agents/arena_agent/*` | Agent 协议、客户端、策略、寻路、渲染 |
| `agents/bots/*` | 随机、启发式、LLM Bot；模式感知 |
| `agents/tools/spectator.py` | 实时观战与 JSONL 回放 |
| `client/index.html`、`style.css`、`app.js` | 独立 Web 客户端与模式可视化 |
| `client/launcher.py` | 本地静态文件启动器 |
| `tests/test_e2e.py` | 跨进程真实对局 |
| `scripts/*.ps1` | 服务端、演示、人类对局编排 |
| `docs/RULES.md`、`PROTOCOL.md`、`HTTP_API.md`、`openapi.yaml` | 对外契约 |

---

### Task 1: 修复战斗引擎审核问题

**Files:**
- Modify: `server/arena_server/engine.py`
- Test: `server/tests/test_endgame.py`

**Interfaces:**
- Consumes: Task 3 的 `Engine.resolve`、`Engine.forfeit`、`Engine.last_events`、`Engine.events_turn`。
- Produces: 无效动作按漏操作计数；回合外判负不混入上一回合事件；其余接口不变。

- [ ] **Step 1: 写失败测试**

```python
class EngineReviewRegressionTests(unittest.TestCase):
    def test_forfeit_after_resolved_turn_does_not_mix_events(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent"),
                             ("C", "agent")],
                   seed=4, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"},
                   "P3": {"type": "wait"}})
        self.assertTrue(e.forfeit("P3"))
        self.assertFalse(e.finished)
        self.assertEqual(e.last_events,
                         [{"type": "forfeit", "player": "P3"}])
        self.assertEqual(e.events_turn, 2)

    def test_invalid_action_does_not_reset_missed_turns(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")],
                   seed=4, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.resolve({"P1": {"type": "wait"}})
        self.assertEqual(e.players["P2"].missed_turns, 1)
        e.resolve({"P1": {"type": "wait"},
                   "P2": {"type": "not-an-action"}})
        self.assertEqual(e.players["P2"].missed_turns, 2)
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_endgame.EngineReviewRegressionTests -v`
Expected: 两个测试 FAIL；第一个显示旧事件被保留，第二个显示漏操作被错误清零。

- [ ] **Step 3: 实现最小修正**

将 `resolve()` 的动作锁定改为只有规范化动作且资源足够才重置漏操作：

```python
for player in alive:
    canonical = self._canonical_action(actions.get(player.id))
    valid = canonical is not None
    if valid and canonical["type"] in COST_ACTIONS:
        cost = {
            "dash": self.rules.dash_cost,
            "attack": self.rules.attack_cost,
            "heal": self.rules.heal_cost,
            "shield": self.rules.shield_cost,
        }[canonical["type"]]
        valid = player.energy >= cost
    if valid:
        player.missed_turns = 0
        chosen[player.id] = canonical
    else:
        player.missed_turns += 1
        chosen[player.id] = {"type": "wait"}
```

将 `forfeit()` 的事件赋值改为替换而非追加：

```python
self.last_events = [{"type": "forfeit", "player": player_id}]
self.events_turn = self.turn
```

- [ ] **Step 4: 运行回归与完整服务器测试**

Run: `cd server; python -m unittest discover -s tests -p "test_*.py" -v`
Expected: 30 项测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/arena_server/engine.py server/tests/test_endgame.py
git commit -m "fix(server): preserve event and missed-turn invariants"
```

---

### Task 2: 模式框架、经典兼容与据点争夺

**Files:**
- Create: `server/arena_server/modes.py`
- Modify: `server/arena_server/engine.py`
- Create: `server/tests/test_modes.py`
- Create: `server/tests/test_rotation.py`

**Interfaces:**
- Consumes: Task 1 的完整 `Engine`。
- Produces:
  - `MODE_ORDER = ("classic", "king", "team", "survival", "bounty")`
  - `MODE_MIN_PLAYERS = {"classic": 2, "king": 2, "team": 4, "survival": 2, "bounty": 2}`
  - `select_mode(requested: str, waiting_count: int, cursor: int) -> tuple[str, int]`
  - `Engine(..., mode: str = "classic")`
  - `Engine.mode_name: str`、`Engine.mode_state: dict`
  - `Engine.mode: GameMode`
  - `start_payload`/`state_payload`/`end_payload` 都包含 `mode` 与 `mode_state`
  - 玩家载荷可按模式追加 `hill_streak`

- [ ] **Step 1: 写失败测试**

```python
class ModeFrameworkTests(unittest.TestCase):
    def test_classic_default_and_payload_compatibility(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")], seed=1,
                   map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        self.assertEqual(e.mode_name, "classic")
        self.assertEqual(e.mode_state, {})
        self.assertEqual(e.start_payload()["mode"], "classic")
        self.assertNotIn("hill_streak", e.state_payload()["players"][0])

    def test_rotation_skips_team_when_only_two_players(self):
        self.assertEqual(select_mode("rotation", 2, 2), ("survival", 4))
        self.assertEqual(select_mode("rotation", 4, 2), ("team", 3))
        self.assertEqual(select_mode("king", 2, 4), ("king", 4))


class KingModeTests(unittest.TestCase):
    def make(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")], seed=1,
                   map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="king")
        e.players["P1"].pos = (7, 7)
        e.players["P2"].pos = (1, 1)
        return e

    def test_zone_score_and_streak(self):
        e = self.make()
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 5)
        self.assertEqual(e.mode_state["streaks"]["P1"], 1)
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 11)
        self.assertEqual(e.mode_state["streaks"]["P1"], 2)
        self.assertIn({"type": "hill_score", "player": "P1", "pos": [7, 7],
                       "points": 6, "streak": 2, "score": 11}, e.last_events)

    def test_leaving_zone_resets_streak(self):
        e = self.make()
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        e.players["P1"].pos = (5, 5)
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 5)
        self.assertEqual(e.mode_state["streaks"]["P1"], 0)

    def test_target_score_ends_match(self):
        e = self.make()
        e.players["P1"].score = 95
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_reason, "score_limit")
        self.assertEqual(e.end_payload()["winner"]["id"], "P1")
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_modes tests.test_rotation -v`
Expected: ImportError（`modes`/`mode` 参数不存在）或断言失败。

- [ ] **Step 3: 实现模式接口**

在 `modes.py` 定义元数据和轮换：

```python
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


def select_mode(requested, waiting_count, cursor):
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
```

定义统一模式钩子接口；本任务实现 `ClassicMode` 与 `KingMode`，后三个模式在 Task 3–5 加入同一工厂：

```python
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


def create_game_mode(engine, name):
    classes = {"classic": ClassicMode, "king": KingMode}
    if name not in classes:
        raise ValueError(f"unknown mode: {name}")
    mode = classes[name]()
    mode.engine = engine
    mode.state = mode.setup()
    return mode
```

- [ ] **Step 4: 将模式钩子接入 Engine**

- 构造参数增加 `mode: str = "classic"`；在玩家与节点初始化完成后保存 `mode_name`，调用 `create_game_mode`，暴露 `mode_state` 属性返回 `self.mode.state`。
- `_player_payload` 改为实例方法，合并 `self.mode.player_fields(player)`。
- 伤害分乘以 `self.mode.damage_multiplier(player, target)`。
- 击杀分使用 `self.mode.kill_reward(player, target)`，不再直接使用固定 `kill_score`。
- 战斗死亡循环后调用 `self.mode.after_deaths(events)`。
- 漏操作判负后调用 `self.mode.after_missed(events)`。
- `_end_reason()` 使用 `self.mode.alive_unit_count()` 与 `self.mode.score_limit_reached()`，顺序为 1 存活、0 存活、目标分、回合上限。
- `end_payload()` 在 `reason != "aborted"` 时使用 `self.mode.winner(standings)`，否则保持 `winner=None`；合并 `self.mode.end_extras()`、`mode`、`mode_state`。
- `forfeit()` 调用 `self.mode.on_forfeit(player_id, self.last_events)`。
- `start_payload()`、`state_payload()`、`end_payload()` 都写入 `mode` 与 `mode_state`。

- [ ] **Step 5: 运行测试**

Run: `cd server; python -m unittest tests.test_modes tests.test_rotation tests.test_combat tests.test_endgame -v`
Expected: 全部 PASS；经典模式现有断言保持通过。

- [ ] **Step 6: 提交**

```bash
git add server/arena_server/modes.py server/arena_server/engine.py server/tests/test_modes.py server/tests/test_rotation.py
git commit -m "feat(server): add mode framework and king of the hill"
```

---

### Task 3: 2v2 团队模式

**Files:**
- Modify: `server/arena_server/modes.py`
- Test: `server/tests/test_modes.py`

**Interfaces:**
- Consumes: Task 2 的 `GameMode` 钩子与 `Engine.mode`。
- Produces: `mode="team"`、玩家 `team`、`mode_state.teams`、`end.team_standings`、队伍 `winner`、`friendly_blocked` 事件。

- [ ] **Step 1: 写失败测试**

```python
class TeamModeTests(unittest.TestCase):
    def make(self):
        e = Engine(Rules(), [("A", "human"), ("B", "agent"),
                             ("C", "human"), ("D", "agent")],
                   seed=2, map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="team")
        for pid, pos in {"P1": (5, 5), "P2": (5, 7),
                         "P3": (6, 5), "P4": (9, 9)}.items():
            e.players[pid].pos = pos
            e.players[pid].energy = 50
        return e

    def test_teams_and_friendly_fire(self):
        e = self.make()
        self.assertEqual(e.state_payload()["players"][0]["team"], "T1")
        self.assertEqual(e.state_payload()["players"][2]["team"], "T2")
        e.players["P2"].pos = (6, 5)
        e.players["P3"].pos = (8, 5)
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"},
                   "P4": {"type": "wait"}})
        self.assertEqual(e.players["P2"].hp, 100)
        self.assertEqual(e.players["P1"].energy, 46)
        self.assertIn({"type": "friendly_blocked", "player": "P1",
                       "target": "P2"}, e.last_events)

    def test_enemy_damage_scores_and_team_total_updates(self):
        e = self.make()
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"},
                   "P4": {"type": "wait"}})
        self.assertEqual(e.players["P3"].hp, 78)
        self.assertEqual(e.players["P1"].score, 22)
        teams = {row["id"]: row for row in e.mode_state["teams"]}
        self.assertEqual(teams["T1"]["score"], 22)
        self.assertEqual(teams["T2"]["alive"], 2)

    def test_team_elimination_has_team_winner(self):
        e = self.make()
        e.forfeit("P3")
        e.forfeit("P4")
        self.assertTrue(e.finished)
        payload = e.end_payload()
        self.assertEqual(payload["reason"], "last_standing")
        self.assertEqual(payload["winner"],
                         {"id": "T1", "name": "Team A", "kind": "team",
                          "members": ["P1", "P2"]})
        self.assertEqual(len(payload["team_standings"]), 2)
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_modes.TeamModeTests -v`
Expected: `unknown mode: team` 或字段缺失。

- [ ] **Step 3: 实现 TeamMode**

- `setup()` 创建 `teams`：`T1=[P1,P2]`、`T2=[P3,P4]`，每项含 `id,name,members,score,alive`。
- `player_fields()` 返回 `team`。
- `friendly()` 返回两名玩家的队伍 ID 相同且非空。
- 攻击阶段在扣 HP 前检查 `friendly()`；成立时只追加 `friendly_blocked`，不扣护盾、HP 或分数。
- `after_missed()` 重算每队 `score=sum(member.score)` 与 `alive=sum(member.alive)`。
- `on_forfeit()` 调用同一队伍状态重算。
- `alive_unit_count()` 返回 `alive > 0` 的队伍数。
- `winner()` 返回获胜队伍对象。
- `end_extras()` 返回按存活人数、总分、总 HP、总能量、ID 排序的 `team_standings`。
- 在 `create_game_mode()` 注册 `"team": TeamMode`。

- [ ] **Step 4: 运行测试**

Run: `cd server; python -m unittest tests.test_modes -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/arena_server/modes.py server/tests/test_modes.py
git commit -m "feat(server): add team 2v2 mode"
```

---

### Task 4: 生存缩圈模式

**Files:**
- Modify: `server/arena_server/modes.py`
- Test: `server/tests/test_modes.py`

**Interfaces:**
- Consumes: Task 2 的 `after_deaths` 钩子。
- Produces: `mode="survival"`、玩家 `in_storm`、`storm_shrink`/`storm_damage` 事件、安全区状态。

- [ ] **Step 1: 写失败测试**

```python
class SurvivalModeTests(unittest.TestCase):
    def make(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent")], seed=3,
                   map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="survival")
        e.players["P1"].pos = (7, 7)
        e.players["P2"].pos = (8, 8)
        return e

    def test_shrink_schedule(self):
        e = self.make()
        expected = {6: (2, 12), 12: (3, 11), 18: (4, 10),
                    24: (5, 9), 30: (6, 8)}
        for turn in range(1, 31):
            e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
            if turn in expected:
                low, high = expected[turn]
                self.assertEqual(e.mode_state["zone"],
                                 {"min": [low, low], "max": [high, high]})
        self.assertIsNone(e.mode_state["next_shrink_turn"])

    def test_storm_true_damage_ignores_shield(self):
        e = self.make()
        e.players["P1"].pos = (1, 1)
        e.players["P1"].shield = 40
        for _ in range(5):
            e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].hp, 88)
        self.assertEqual(e.players["P1"].shield, 40)
        self.assertIn({"type": "storm_damage", "player": "P1",
                       "amount": 12, "hp": 88}, e.last_events)
        self.assertTrue(e.state_payload()["players"][0]["in_storm"])

    def test_storm_death_has_no_killer_or_score(self):
        e = self.make()
        e.players["P1"].pos = (1, 1)
        e.players["P1"].hp = 5
        for _ in range(6):
            e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertFalse(e.players["P1"].alive)
        self.assertEqual(e.players["P2"].score, 0)
        self.assertIn({"type": "death", "player": "P1", "killer": None},
                      e.last_events)
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_modes.SurvivalModeTests -v`
Expected: `unknown mode: survival`。

- [ ] **Step 3: 实现 SurvivalMode**

- `setup()` 返回初始 `zone={"min":[1,1],"max":[13,13]}`、`next_shrink_turn=6`、`storm_damage=12`。
- `player_fields()` 根据当前位置与当前区域返回 `in_storm`。
- `after_deaths()` 在当前 `engine.turn` 等于 `6/12/18/24/30` 时：
  - 四边各收缩 1，最小边界为 6、最大边界为 8。
  - 追加 `storm_shrink`。
  - 对仍存活且在新区域外的玩家扣 12 HP，忽略护盾，不加分。
  - 追加 `storm_damage`；HP 归零时追加 `death killer=null`。
  - 更新 `next_shrink_turn`，30 回合后为 `None`。
- 在工厂注册 `"survival": SurvivalMode`。

- [ ] **Step 4: 运行测试**

Run: `cd server; python -m unittest tests.test_modes -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/arena_server/modes.py server/tests/test_modes.py
git commit -m "feat(server): add survival shrinking-zone mode"
```

---

### Task 5: 赏金乱斗模式

**Files:**
- Modify: `server/arena_server/modes.py`
- Test: `server/tests/test_modes.py`

**Interfaces:**
- Consumes: Task 2 的伤害/击杀钩子与 `after_missed`。
- Produces: `mode="bounty"`、玩家 `bounty_target/bounty_streak`、赏金事件与 150 分结束。

- [ ] **Step 1: 写失败测试**

```python
class BountyModeTests(unittest.TestCase):
    def make(self):
        e = Engine(Rules(), [("A", "agent"), ("B", "agent"),
                             ("C", "agent")],
                   seed=5, map_data=MapData(15, 15, frozenset(), NODE_POINTS),
                   mode="bounty")
        for pid, pos in {"P1": (5, 5), "P2": (6, 5),
                         "P3": (9, 9)}.items():
            e.players[pid].pos = pos
            e.players[pid].energy = 50
        return e

    def test_initial_cycle_and_double_damage_score(self):
        e = self.make()
        self.assertEqual(e.mode_state["targets"],
                         {"P1": "P2", "P2": "P3", "P3": "P1"})
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"}})
        self.assertEqual(e.players["P2"].hp, 78)
        self.assertEqual(e.players["P1"].score, 44)
        damage = next(ev for ev in e.last_events if ev["type"] == "damage")
        self.assertTrue(damage["bounty"])

    def test_target_kill_reward_and_retarget(self):
        e = self.make()
        e.players["P2"].hp = 5
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"}})
        self.assertEqual(e.players["P1"].kills, 1)
        self.assertEqual(e.players["P1"].score, 60)
        self.assertEqual(e.players["P1"].bounty_streak, 1)
        self.assertEqual(e.mode_state["targets"]["P1"], "P3")
        self.assertEqual(e.mode_state["targets"]["P3"], "P1")
        self.assertIn({"type": "bounty_complete", "player": "P1",
                       "target": "P2", "bonus": 50, "streak": 1},
                      e.last_events)

    def test_non_target_kill_has_no_streak_bonus(self):
        e = self.make()
        e.players["P2"].pos = (7, 5)
        e.players["P3"].pos = (6, 5)
        e.players["P3"].hp = 5
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 35)
        self.assertEqual(e.players["P1"].bounty_streak, 0)

    def test_target_score_limit(self):
        e = self.make()
        e.players["P1"].score = 145
        e.players["P2"].hp = 50
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "wait"}, "P3": {"type": "wait"}})
        self.assertEqual(e.players["P1"].score, 155)
        self.assertEqual(e.end_reason, "score_limit")
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_modes.BountyModeTests -v`
Expected: `unknown mode: bounty`。

- [ ] **Step 3: 实现 BountyMode**

- `setup()` 按 ID 循环建立 `targets`，`target_score=150`；每名玩家 `bounty_streak=0`。
- `player_fields()` 返回 `bounty_target` 与 `bounty_streak`。
- `damage_multiplier()` 在目标是当前赏金目标时返回 2，否则 1。
- `kill_reward()`：
  - 目标击杀返回 `25 + 25 + min(previous_streak,4)*5`。
  - 非目标击杀返回 25。
- `after_deaths()` 解析本回合 `death` 事件，对赏金击杀追加 `bounty_complete` 并增加击杀者连杀。
- `after_missed()` 为所有存活玩家按 ID 循环重找下一名存活且非自己的玩家，目标变化时追加 `bounty_retarget`；死亡玩家目标设为 `None`、连杀清零。
- `score_limit_reached()` 检查任一玩家分数是否达到 150，包含同回合达到目标后死亡的玩家。
- 在工厂注册 `"bounty": BountyMode`。

- [ ] **Step 4: 运行测试**

Run: `cd server; python -m unittest tests.test_modes -v`
Expected: 全部 PASS，包括三名玩家均存活时的 `score_limit` 结束优先级。

- [ ] **Step 5: 提交**

```bash
git add server/arena_server/modes.py server/tests/test_modes.py
git commit -m "feat(server): add bounty hunt mode"
```

---

### Task 6: 带模式支持的大厅、对局循环、TCP 网关与服务端

**Files:**
- 完整执行基线计划 Task 4 的所有文件与测试。
- Modify: `server/arena_server/config.py`
- Modify: `server/arena_server/lobby.py`
- Modify: `server/arena_server/server.py`
- Modify: `server/arena_server/match.py`
- Test: `server/tests/test_tcp.py`
- Test: `server/tests/test_rotation.py`

**Interfaces:**
- Consumes: Task 2–5 的 `Engine(mode=...)`、`select_mode`、模式载荷。
- Produces: 基线 Task 4 的全部接口，并满足：
  - `ServerConfig.mode="rotation"`
  - CLI `--mode`
  - `GameServer.start() -> tuple[int, int | None]`（HTTP 仍为 Task 7 接入）
  - `start/state/end` 自动包含 `mode/mode_state`
  - 大厅包含下一局 `mode/mode_label/mode_description`

- [ ] **Step 1: 写失败集成测试**

在基线 `test_tcp.py` 的两个 Agent 测试中断言：

```python
self.assertEqual(start1["mode"], "classic")
self.assertIn("mode_state", start1)
self.assertEqual(state["mode"], "classic")
self.assertIn("mode_state", state)
```

新增固定据点模式测试：服务端使用 `mode="king"`，两名 Agent 加入后 `start["mode"] == "king"`，`start["mode_state"]["target_score"] == 100`。

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_tcp -v`
Expected: 基线 GameServer 尚未实现而失败；实现后若模式字段缺失则断言失败。

- [ ] **Step 3: 实现基线 Task 4 并应用模式增量**

严格实现基线计划 Task 4 的 `protocol.py`、`participants.py`、`lobby.py`、`match.py`、`logging_utils.py`、`tcp_gateway.py`、`server.py`、`__main__.py` 与三个 TCP 集成测试。额外完成：

- `ServerConfig` 增加 `mode: str = "rotation"`；CLI 增加 `--mode choices=[...]`。
- `GameServer` 保存 `mode_cursor=0`。
- 大厅循环在决定开始倒计时前调用 `select_mode(config.mode, len(waiting), mode_cursor)`；固定团队模式未满 4 人不开始倒计时。
- `_start_match()` 使用选定模式创建 `Engine(..., mode=mode_name)`；只有真实开局后更新 `mode_cursor`。
- `Lobby.snapshot()` 接收模式信息并返回 `mode/mode_label/mode_description`。
- `Match` 原样发送 `Engine.start_payload/state_payload/end_payload`，不删除模式字段。
- JSONL 日志保留完整 `start/state/end`，因此自动包含模式信息。
- 未知 `--mode` 由 argparse 拒绝并显示可选值。

- [ ] **Step 4: 增加轮换单元测试**

```python
class RotationSelectionTests(unittest.TestCase):
    def test_two_players_skip_team(self):
        self.assertEqual(select_mode("rotation", 2, 0), ("classic", 1))
        self.assertEqual(select_mode("rotation", 2, 1), ("king", 2))
        self.assertEqual(select_mode("rotation", 2, 2), ("survival", 4))

    def test_four_players_allow_team(self):
        self.assertEqual(select_mode("rotation", 4, 2), ("team", 3))

    def test_fixed_mode_does_not_advance(self):
        self.assertEqual(select_mode("bounty", 2, 4), ("bounty", 4))
```

- [ ] **Step 5: 运行测试**

Run: `cd server; python -m unittest tests.test_tcp tests.test_rotation tests.test_modes -v`
Expected: 全部 PASS；3 个基线 TCP 测试和新增模式断言通过。

- [ ] **Step 6: 提交**

```bash
git add server/arena_server server/tests/test_tcp.py server/tests/test_rotation.py
git commit -m "feat(server): add lobby, match loop and mode-aware TCP gateway"
```

---

### Task 7: HTTP API、会话与模式视图

**Files:**
- 完整执行基线计划 Task 5 的所有文件与测试。
- Modify: `server/arena_server/server.py`
- Modify: `server/arena_server/http_api.py`
- Test: `server/tests/test_http_api.py`

**Interfaces:**
- Consumes: Task 6 的 `GameServer`、`Match`、`Participant`。
- Produces: 基线 Task 5 的全部 HTTP 接口，并满足：
  - `GameServer.start() -> tuple[int, int]`
  - `view.lobby.mode/mode_label/mode_description`
  - `view.match.mode/mode_state`
  - `view.result.mode/mode_state`
  - 团队结果保留 `team_standings`，`winner.kind` 可为 `team`

- [ ] **Step 1: 写失败测试**

在基线 HTTP 混合对局测试中增加：

```python
self.assertIn(match["mode"], {"classic", "king", "survival", "bounty"})
self.assertIn("mode_state", match)
self.assertIn(final_view["result"]["mode"],
              {"classic", "king", "survival", "bounty"})
```

新增长驻大厅视图测试：两名玩家排队时，`view["lobby"]["mode"]` 与 `view["lobby"]["mode_description"] 均存在。

- [ ] **Step 2: 运行并确认失败**

Run: `cd server; python -m unittest tests.test_http_api -v`
Expected: ImportError 或模式字段缺失。

- [ ] **Step 3: 实现基线 Task 5 并应用模式增量**

严格实现基线计划 Task 5 的 `sessions.py`、`http_api.py`、`GameServer` HTTP 生命周期、token/CORS/限流/错误映射与三个 HTTP 集成测试。额外完成：

- `server.view_for()` 的大厅分支合并当前下一局模式信息。
- 比赛分支直接使用 `Match.view_for()`，其中包含 `Engine` 的 `mode/mode_state`。
- 结束分支保存完整 `end_payload()`，包括模式、模式状态和团队排名。
- `rules_payload()["defaults"]` 增加 `mode`。
- HTTP 状态码映射保持基线要求；`score_limit` 是结束原因，不是动作错误。
- 服务端任何路径仍不返回静态文件。

- [ ] **Step 4: 运行测试**

Run: `cd server; python -m unittest tests.test_http_api tests.test_tcp tests.test_rotation -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/arena_server/server.py server/arena_server/sessions.py server/arena_server/http_api.py server/tests/test_http_api.py
git commit -m "feat(server): add HTTP sessions and mode-aware mixed matches"
```

---

### Task 8: Agent SDK、模式感知 Bot 与终端观战

**Files:**
- 完整执行基线计划 Task 6 的所有文件与测试。
- Modify: `agents/bots/heuristic.py`
- Modify: `agents/bots/llm_agent.py`
- Test: `agents/tests/test_pathfinding.py`
- Test: `agents/tests/test_llm.py`

**Interfaces:**
- Consumes: Task 6–7 下发的 `start.mode`、`mode_state`、玩家 `team/bounty_target/in_storm`。
- Produces: 基线 Task 6 的全部 SDK/Bot/观战接口，并满足：
  - 启发式 Bot 在四种新模式中选择正确目标。
  - LLM 提示词包含模式状态。
  - 观战器忽略未知事件仍可渲染，能显示新增事件文本。

- [ ] **Step 1: 写失败测试**

```python
class ModeAwareHeuristicTests(unittest.TestCase):
    def start(self, mode, state):
        return {"you": "P1", "mode": mode, "mode_state": state,
                "rules": {"max_hp": 100, "max_energy": 100,
                          "attack": {"cost": 8},
                          "dash": {"cost": 18},
                          "heal": {"cost": 25, "amount": 25},
                          "shield": {"cost": 12, "amount": 26, "max": 40},
                          "gather": {"energy": 30}},
                "arena": {"width": 15, "height": 15, "walls": []},
                "players": []}

    def state(self, me, others, nodes=None):
        return {"turn": 1, "you": "P1",
                "players": [{"id": "P1", "pos": me, "hp": 100,
                             "energy": 80, "shield": 0, "alive": True,
                             "team": "T1", "bounty_target": "P2",
                             "in_storm": True}, *others],
                "nodes": nodes or [], "events": []}

    def test_survival_moves_toward_safe_zone(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(self.start("survival", {
            "zone": {"min": [6, 6], "max": [8, 8]}}))
        action = policy.decide(self.state([1, 1], []))
        self.assertIn(action["type"], {"move", "dash"})

    def test_team_does_not_target_friendly_player(self):
        policy = HeuristicPolicy("aggressive")
        policy.on_start(self.start("team", {"teams": []}))
        friendly = [{"id": "P2", "pos": [2, 1], "hp": 100,
                     "energy": 80, "shield": 0, "alive": True,
                     "team": "T1"}]
        action = policy.decide(self.state([1, 1], friendly))
        self.assertNotEqual(action, {"type": "attack", "dir": "e"})

    def test_bounty_prefers_assigned_target(self):
        policy = HeuristicPolicy("balanced")
        policy.on_start(self.start("bounty", {
            "target_score": 150, "targets": {"P1": "P2"}}))
        others = [{"id": "P2", "pos": [3, 1], "hp": 100,
                   "energy": 80, "shield": 0, "alive": True},
                  {"id": "P3", "pos": [1, 3], "hp": 100,
                   "energy": 80, "shield": 0, "alive": True}]
        action = policy.decide(self.state([1, 1], others))
        self.assertEqual(action, {"type": "move", "dir": "e"})
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd agents; python -m unittest discover -s tests -v`
Expected: 基线 SDK 未实现而失败；实现后新增模式测试若未处理模式状态则失败。

- [ ] **Step 3: 实现基线 Task 6 并应用模式增量**

严格实现基线计划 Task 6 的协议、SDK、策略、BFS、ASCII 渲染、随机 Bot、启发式 Bot、LLM Agent、终端观战/回放与四个测试文件。额外完成：

- `HeuristicPolicy.on_start` 保存 `mode` 与 `mode_state`。
- 目标优先级：
  - `survival` 且 `in_storm`：BFS 到最近安全格。
  - `king`：BFS 到中心区域。
  - `team`：敌人列表排除同队玩家。
  - `bounty`：优先选择 `bounty_target`。
- 所有移动仍本地检查墙、占用、能量和节点冷却。
- `LlmPolicy` 的 prompt 加入 `mode/mode_state` 与模式说明；单次 LLM 请求超时必须小于服务端 `tick_ms`，截止后返回的动作只记录为本地过期，不追溯提交。
- 文档与 CLI 示例明确：LLM 对局使用 `--tick-ms 30000` 或 `--tick-ms 60000`；所有玩家共享同一决策窗口，没有实时操作。
- `render_board` 可显示模式标题；无法绘制的区域使用状态行文本，不抛异常。
- 终端观战遇到 `hill_score/storm_shrink/storm_damage/bounty_complete/bounty_retarget/friendly_blocked` 时输出可读摘要。

- [ ] **Step 4: 运行测试与真实 Bot 联调**

Run: `cd agents; python -m unittest discover -s tests -v`
Expected: 全部 PASS。

使用 Task 6 的真实服务端，以 `--mode king` 启动两名 Bot，确认至少完成一局且无异常退出。

- [ ] **Step 5: 提交**

```bash
git add agents
git commit -m "feat(agents): add SDK, mode-aware bots and terminal spectator"
```

---

### Task 9: 独立 Web 客户端与模式可视化

**Files:**
- 完整执行基线计划 Task 7 的所有文件与测试。
- Modify: `client/index.html`
- Modify: `client/style.css`
- Modify: `client/app.js`
- Test: `client/tests/test_static.py`

**Interfaces:**
- Consumes: Task 7 的 HTTP `view`。
- Produces: 基线客户端全部功能，并满足：
  - 大厅显示下一局模式。
  - 对局显示模式徽章与对应 HUD/棋盘覆盖层。
  - 结算识别 `score_limit` 与 `winner.kind == "team"`。

- [ ] **Step 1: 写失败静态测试**

```python
def test_mode_rendering_hooks_exist(self):
    app = (CLIENT / "app.js").read_text(encoding="utf-8")
    for token in ("mode_state", "hill_streak", "in_storm",
                  "bounty_target", "team_standings", "score_limit"):
        self.assertIn(token, app)
    self.assertIn("textContent", app)
    self.assertNotIn("innerHTML", app)
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd client; python -m unittest discover -s tests -v`
Expected: 文件不存在或模式渲染标记缺失。

- [ ] **Step 3: 实现基线 Task 7 并应用模式增量**

严格实现基线计划 Task 7 的四个页面、霓虹样式、API 轮询、Canvas、键鼠操作、localStorage 恢复、断线重连、结算/再来一局、安全 launcher 与静态测试。额外完成：

- `renderLobby` 显示 `lobby.mode_label` 与 `mode_description`。
- `renderGame` 显示 `match.mode` 徽章。
- `drawBoard`：
  - `king` 绘制 `mode_state.zone` 覆盖层。
  - `survival` 绘制安全区外风暴遮罩。
  - `team` 使用队伍配色边框。
  - `bounty` 在自己与目标之间绘制标记或目标高亮。
- `renderHud` 显示 `hill_streak`、`in_storm`、`bounty_target/bounty_streak` 与队伍。
- `renderResult`：
  - `reason == "score_limit"` 显示“达到目标分数”。
  - `winner.kind == "team"` 显示队伍名称与成员。
  - 有 `team_standings` 时渲染队伍排名。
- 所有新增动态文本仍用 `textContent`。

- [ ] **Step 4: 运行静态测试**

Run: `cd client; python -m unittest discover -s tests -v`
Expected: 全部 PASS。

- [ ] **Step 5: 浏览器验收**

启动真实服务端、两名 Bot 与 launcher，至少完成：

1. 大厅显示模式。
2. 一局 `king` 的中心区域与占领条正常。
3. 鼠标和键盘各提交一次动作。
4. 刷新后恢复。
5. 结算与再来一局正常。
6. 控制台无报错，Network 无外部域名。

- [ ] **Step 6: 提交**

```bash
git add client
git commit -m "feat(client): add standalone mode-aware neon web client"
```

---

### Task 10: 跨进程 E2E 与 PowerShell 编排

**Files:**
- 完整执行基线计划 Task 8 的所有文件与测试。
- Modify: `tests/test_e2e.py`
- Modify: `scripts/start_server.ps1`
- Modify: `scripts/demo.ps1`
- Modify: `scripts/play.ps1`

**Interfaces:**
- Consumes: Task 6–9 的完整可运行系统。
- Produces: 基线 E2E 与脚本，并覆盖非经典模式和 4 人团队战。

- [ ] **Step 1: 写失败 E2E**

保留基线“Human + BotA + BotB 完成经典对局”测试，并新增：

```python
def test_king_mode_human_and_agents_finish(self):
    # 与基线测试相同地启动服务端，但增加 --mode king。
    # Human 通过 HTTP，BotA/BotB 通过 TCP。
    # 断言 start/state/view 中 mode == "king"。
    # 断言最终 result["mode"] == "king" 且三名玩家都在 standings。


def test_team_mode_four_participants_finish(self):
    # 启动 --mode team，Human 通过 HTTP，三个随机 Bot 通过 TCP。
    # 断言四名玩家、T1/T2 各两人、最终 team_standings 两项。
    # 断言 winner.kind == "team"。
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m unittest tests.test_e2e -v`
Expected: 基线脚本/系统尚未完成而失败，或模式断言失败。

- [ ] **Step 3: 实现基线 Task 8 并应用模式增量**

严格实现基线计划 Task 8 的跨进程测试和三个 PowerShell 5.1 兼容脚本。额外完成：

- `start_server.ps1` 增加 `-Mode rotation` 并透传 `--mode`。
- `demo.ps1` 默认使用 `rotation`，3 个 Bot 在 2 人门槛下会跳过团队模式。
- `play.ps1` 默认使用 `rotation`，2 个 Bot + 1 人类可连续体验非团队模式。
- 所有脚本用 `$PSScriptRoot` 推导路径，`finally` 清理子进程。
- E2E 使用动态空闲端口，断言服务器退出、无残留子进程、HTTP 根路径 404 JSON。

- [ ] **Step 4: 运行 E2E**

Run: `python -m unittest tests.test_e2e -v`
Expected: 经典混合对局、据点混合对局、4 人团队战全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add tests scripts
git commit -m "test: add multi-mode end-to-end matches and scripts"
```

---

### Task 11: 文档、OpenAPI 与最终验收

**Files:**
- 完整执行基线计划 Task 9 的所有文件。
- Modify: `README.md`
- Modify: `server/README.md`
- Modify: `agents/README.md`
- Modify: `docs/RULES.md`
- Modify: `docs/PROTOCOL.md`
- Modify: `docs/HTTP_API.md`
- Modify: `docs/openapi.yaml`

**Interfaces:**
- Consumes: Task 1–10 的最终实现与测试结果。
- Produces: 与实现完全一致的运行说明、规则、协议、HTTP API、OpenAPI 与部署说明。

- [ ] **Step 1: 更新文档内容**

在基线 Task 9 要求的全部文档中增加：

- 五种模式名称、最低人数、精确数值与结束原因。
- 默认自动轮换、跳过团队模式规则、`--mode` 固定模式示例。
- `mode/mode_state`、玩家模式字段、新增事件、`score_limit`、团队 `winner/team_standings`。
- 各 Bot 的模式感知行为。
- 严格回合制说明、LLM 思考窗口建议（`--tick-ms 30000/60000`）、截止后动作不追溯生效。
- 客户端各模式视觉与操作不变说明。
- 远程部署、防火墙、无 TLS 风险与零依赖说明。

OpenAPI 中：

- `ServerConfig`/默认值增加 `mode`。
- `LobbyView` 增加 `mode/mode_label/mode_description`。
- `MatchView` 增加 `mode/mode_state`。
- `PlayerView` 增加可选 `team/hill_streak/in_storm/bounty_target/bounty_streak`。
- `EndedView` 的 reason 枚举增加 `score_limit`，winner 增加 `kind`，结果增加可选 `team_standings`。

- [ ] **Step 2: 校验文档**

Run:

```bash
python -c "import pathlib; p=pathlib.Path('docs/openapi.yaml'); text=p.read_text(encoding='utf-8'); assert '/health' in text and '/actions' in text and 'score_limit' in text and 'mode_state' in text; print('openapi text ok')"
```

Expected: `openapi text ok`。若本机有 PyYAML，再执行基线计划的 YAML 解析校验；PyYAML 不是运行依赖。

- [ ] **Step 3: 占位符与外部依赖检查**

Run:

```bash
git grep -n "TODO\|TBD\|FIXME\|PLAN_PART" -- . ":(exclude)docs/superpowers/plans/*"
git grep -n "cdn.\|unpkg.com\|jsdelivr\|googleapis" -- client
```

Expected: 均无输出。

- [ ] **Step 4: 全量测试**

Run:

```bash
cd server; python -m unittest discover -s tests -p "test_*.py" -v
cd ../agents; python -m unittest discover -s tests -v
cd ../client; python -m unittest discover -s tests -v
cd ..; python -m unittest discover -s tests -v
```

Expected: 四组全部 PASS。

- [ ] **Step 5: 最终手工验收**

1. 真实服务端写 JSONL，日志包含模式字段。
2. 两个 Bot + 人类完成至少两个不同模式。
3. 四个参与者完成团队战。
4. 关闭 Bot 后立即判负，其余玩家继续。
5. 刷新 Web 客户端恢复当前模式对局。
6. 终端观战与回放识别新增事件。
7. 服务端根路径和 `/client/*` 均返回 JSON 404。
8. 浏览器控制台无报错，无外部资源请求。

- [ ] **Step 6: 提交**

```bash
git add README.md server/README.md agents/README.md docs/RULES.md docs/PROTOCOL.md docs/HTTP_API.md docs/openapi.yaml
git commit -m "docs: document multi-mode gameplay and final operations"
```

---

## 最终验收清单

- [ ] Task 3 审核问题修复，经典模式 28 项原测试与新增回归全部通过。
- [ ] 五种模式均由服务端权威结算，模式单元测试全部通过。
- [ ] 默认自动轮换，2–3 人跳过团队战，4 人可玩团队战。
- [ ] TCP Agent 与 HTTP 人类可在同一非经典模式完成真实对局。
- [ ] 四个真实参与者可完成团队战并产生队伍结算。
- [ ] Agent SDK、随机/启发式/LLM Bot、终端观战与回放可用。
- [ ] Web 客户端支持五种模式的可视化、刷新恢复、重连、结算与再来一局。
- [ ] `server`、`agents`、`client`、根 E2E 四组测试全部通过。
- [ ] README、规则、TCP、HTTP、OpenAPI、脚本和部署说明齐全。
- [ ] 零第三方运行依赖，Windows PowerShell 5.1 与 Python 3.10 可执行文档命令。
- [ ] 工作树干净，所有任务按 Task 顺序提交。
