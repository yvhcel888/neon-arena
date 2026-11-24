# NEON ARENA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `D:\NeonArena` 交付可运行的服务端、独立人类 Web 客户端、Agent SDK 与示例 Bot，支持人类与多个远程 Agent 通过 IP:端口混合对局。

**Architecture:** Python 3.10+ 标准库权威服务端，同时暴露 TCP NDJSON（Agent，:7777）与 HTTP JSON（人类/自定义客户端，:8080）；人类客户端是独立静态 Web 应用，Agent SDK 是独立 Python 包。三者只通过文档化协议通信，不共享运行时代码。

**Tech Stack:** Python 3.10+（asyncio、unittest、http 协议手写解析）、原生 HTML/CSS/JS Canvas、PowerShell 编排脚本、Git。

**Spec:** `D:\NeonArena\docs\superpowers\specs\2026-11-23-neon-arena-design.md`（实现时必须先读；本计划中“规格 §X”指该文档章节）

## Global Constraints

- Python 最低 3.10，**禁止第三方运行依赖**；服务端/Agent 只用标准库；客户端无 CDN、无构建工具。
- 三个独立目录：`server/`、`agents/`、`client/`；服务端不导入 Agent/客户端代码，不返回 HTML/JS/CSS。
- 服务端端口：TCP Agent `7777`、HTTP API `8080`；客户端本地 launcher `8090`。均可配置。
- 客户端只是 HTTP API 消费者；游戏规则、校验、结算只在服务端。
- 所有网络字段遵循规格 §5、§6；坐标 `[x,y]`，方向 `n/e/s/w`。
- 人类与 Agent 混用同一大厅/对局；每局 2–4 人，单活动对局，其余排队。
- 测试框架使用 `unittest`；测试命令从各自目录运行；每个 Task 独立提交 Git。
- 不生成占位功能：每个 Task 的测试和实现必须真实可跑。
- 编码 UTF-8；Windows 主路径，兼容 Linux/macOS；日志/控制台为 ASCII 或 UTF-8。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `server/arena_server/config.py` | `Rules`/`ServerConfig`、默认数值、CLI 解析 |
| `server/arena_server/engine.py` | 地图、玩家、动作校验、结算、事件、计分、序列化 |
| `server/arena_server/protocol.py` | 协议版本、错误码、消息辅助 |
| `server/arena_server/participants.py` | 统一 TCP/HTTP 参与者模型 |
| `server/arena_server/lobby.py` | 排队、倒计时、开赛 |
| `server/arena_server/match.py` | 单局循环、动作收集、计时、结束、日志 |
| `server/arena_server/tcp_gateway.py` | TCP 连接、NDJSON、路由、观战 |
| `server/arena_server/http_api.py` | 独立 HTTP/JSON API、CORS、轮询视图 |
| `server/arena_server/sessions.py` | HTTP session/token/清理 |
| `server/arena_server/server.py` | 组装、生命周期、大厅广播、混合视图 |
| `server/arena_server/__main__.py` | `python -m arena_server` |
| `agents/arena_agent/protocol.py` | Agent 侧协议常量与编解码 |
| `agents/arena_agent/client.py` | 阻塞式 TCP Agent 客户端与回调循环 |
| `agents/arena_agent/policy.py` | `Policy` 基类、动作构造、规则访问 |
| `agents/arena_agent/pathfinding.py` | BFS/方向工具 |
| `agents/arena_agent/render.py` | ASCII 观战渲染 |
| `agents/bots/heuristic.py` | 三种启发式风格 |
| `agents/bots/random_bot.py` | 随机合法动作 |
| `agents/bots/llm_agent.py` | OpenAI 兼容 LLM 模板 |
| `agents/tools/spectator.py` | 实时观战/日志回放 CLI |
| `client/index.html` | 独立客户端结构 |
| `client/style.css` | 霓虹 UI |
| `client/app.js` | API 轮询、Canvas、输入、重连 |
| `client/launcher.py` | 仅本地静态文件启动器 |
| `tests/test_e2e.py` | 跨进程服务端+Agent+人类 API 端到端 |
| `docs/PROTOCOL.md` / `HTTP_API.md` / `RULES.md` / `openapi.yaml` | 对外契约 |
| `scripts/start_server.ps1` / `demo.ps1` / `play.ps1` | 编排 |
| `README.md` + 各目录 README | 快速开始与部署 |
| `.gitignore` | 忽略日志、缓存 |

### 规格覆盖对照

| 规格章节 | 对应任务 |
|---|---|
| §2 客户端/服务端分离、部署 | Task 4（TCP）、Task 5（HTTP）、Task 7（独立客户端）、Task 8（跨进程验收） |
| §3 游戏规则、结算、计分、胜负 | Task 1（地图）、Task 2（移动/资源）、Task 3（战斗/结束）、Task 9（RULES.md） |
| §4 服务端模块、并发、大厅、生命周期 | Task 4（大厅/Match/TCP）、Task 5（HTTP/会话） |
| §5 TCP Agent 协议 | Task 4（网关）、Task 6（SDK 对端）、Task 9（PROTOCOL.md） |
| §6 HTTP API、CORS、视图 | Task 5（实现）、Task 7（消费）、Task 9（HTTP_API.md/OpenAPI） |
| §7 参考人类客户端 | Task 7、Task 8（脚本联调）、Task 9（验收） |
| §8 Agent SDK 与示例 Bot | Task 6、Task 9（agents/README） |
| §9 观战、JSONL 日志、回放 | Task 4（日志）、Task 6（观战器/回放）、Task 9（验收） |
| §10 数据模型、坐标、版本 | Task 2（Engine 序列化）、Task 4/5（协议包装） |
| §11 目录结构 | 所有 Task 的 Files 列表 |
| §12 配置与运行 | Task 1（ServerConfig）、Task 4（CLI）、Task 5（HTTP 参数）、Task 9（README） |
| §13 安全与健壮性 | Task 4（限流/上限/断线）、Task 5（token/请求限制/CORS）、Task 9（部署风险） |
| §14 测试与验收 | Task 1–8 的测试步骤 + 本计划末尾 DoD |
| §15 里程碑 | Task 1–9 顺序对应 M1–M6 |
| §16 风险与取舍 | Task 9 README/部署文档 |

---

### Task 1: Server 包骨架与可复现地图

**Files:**
- Create: `.gitignore`
- Create: `server/arena_server/__init__.py`
- Create: `server/arena_server/config.py`
- Create: `server/arena_server/engine.py`（本任务只含地图/常量）
- Create: `server/tests/__init__.py`
- Create: `server/tests/test_map.py`

**Interfaces:**
- Produces: `Rules` dataclass（字段见规格 §5.4）；`ServerConfig` dataclass（服务端全部可配置项，默认值与规格 §12.1 一致）；`MapData(width, height, walls: frozenset[tuple[int,int]], nodes: tuple[tuple[int,int],...])`；`generate_map(seed: int) -> MapData`；`SPAWN_POINTS`、`NODE_POINTS`、`arena_connected(map_data) -> bool`。

- [ ] **Step 1: 写失败测试**

```gitignore
# .gitignore
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
logs/
*.log
.pytest_cache/
.idea/
.vscode/
Thumbs.db
.DS_Store
```

```python
# server/tests/test_map.py
import unittest
from arena_server.engine import SPAWN_POINTS, NODE_POINTS, generate_map, arena_connected


class TestMap(unittest.TestCase):
    def test_same_seed_same_map(self):
        self.assertEqual(generate_map(123).walls, generate_map(123).walls)

    def test_different_seeds_vary(self):
        signatures = {tuple(sorted(generate_map(s).walls)) for s in range(10)}
        self.assertGreater(len(signatures), 1)

    def test_rotational_symmetry(self):
        for seed in (1, 7, 42, 999):
            walls = generate_map(seed).walls
            self.assertEqual(
                {(14 - x, 14 - y) for x, y in walls},
                set(walls),
            )

    def test_spawns_and_nodes_clear_and_connected(self):
        for seed in range(1, 51):
            m = generate_map(seed)
            for pos in list(SPAWN_POINTS) + list(NODE_POINTS):
                self.assertNotIn(pos, m.walls)
            self.assertTrue(arena_connected(m), f"seed {seed} disconnected")

    def test_nodes_present(self):
        m = generate_map(5)
        self.assertEqual(tuple(m.nodes), NODE_POINTS)
```

- [ ] **Step 2: 运行并确认失败**

`cd server; python -m unittest tests.test_map -v`
Expected: FAIL/ImportError（`generate_map` 未定义）。

- [ ] **Step 3: 实现 config + 地图生成**

```python
# server/arena_server/config.py
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

    def rules(self) -> Rules:
        return Rules(turn_limit=self.turn_limit)
```

```python
# server/arena_server/engine.py 顶部
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import random

WIDTH, HEIGHT = 15, 15
SPAWN_POINTS = ((1, 1), (13, 13), (13, 1), (1, 13))
NODE_POINTS = ((7, 7), (7, 3), (3, 7), (11, 7), (7, 11))

@dataclass(frozen=True)
class MapData:
    width: int
    height: int
    walls: frozenset[tuple[int, int]]
    nodes: tuple[tuple[int, int], ...]

def _reserved() -> set[tuple[int, int]]:
    reserved = set()
    for x, y in (*SPAWN_POINTS, *NODE_POINTS):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                reserved.add((x + dx, y + dy))
    return reserved

def _connected(walls, points) -> bool:
    points = set(points)
    start = next(iter(points))
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if not (0 <= nxt[0] < WIDTH and 0 <= nxt[1] < HEIGHT):
                continue
            if nxt in walls or nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return points <= seen

def arena_connected(map_data: MapData) -> bool:
    return _connected(map_data.walls, (*SPAWN_POINTS, *NODE_POINTS))

def generate_map(seed: int) -> MapData:
    reserved = _reserved()
    candidates = []
    for x in range(1, WIDTH - 1):
        for y in range(1, HEIGHT - 1):
            pos = (x, y)
            rot = (WIDTH - 1 - x, HEIGHT - 1 - y)
            if pos >= rot or pos in reserved or rot in reserved:
                continue
            if pos == rot:
                continue
            candidates.append((pos, rot))
    for attempt in range(100):
        rng = random.Random(seed * 1009 + attempt)
        rng.shuffle(candidates)
        walls = set()
        for a, b in candidates:
            if len(walls) >= 20:
                break
            if a not in walls and b not in walls:
                walls.add(a)
                walls.add(b)
        m = MapData(WIDTH, HEIGHT, frozenset(walls), NODE_POINTS)
        if arena_connected(m):
            return m
    return MapData(WIDTH, HEIGHT, frozenset(), NODE_POINTS)
```

- [ ] **Step 4: 运行测试确认通过**

`cd server; python -m unittest tests.test_map -v`
Expected: 5 tests PASS。

- [ ] **Step 5: Commit**

```powershell
cd D:\NeonArena
git add .gitignore server/arena_server/__init__.py server/arena_server/config.py server/arena_server/engine.py server/tests/__init__.py server/tests/test_map.py
git commit -m "feat(server): add rules config and symmetric map generation"
```

---

### Task 2: 引擎动作校验、玩家状态与移动结算

**Files:**
- Modify: `server/arena_server/engine.py`
- Create: `server/tests/test_movement.py`

**Interfaces:**
- Produces:
  - `ActionError(Exception)`，属性 `code: str`、`message: str`
  - `Player` dataclass 字段：`id,name,kind,pos,hp,shield,energy,score,alive,damage_dealt,kills,gathered,forfeited,missed_turns`
  - `Node` dataclass 字段：`pos,cooldown`，属性 `active == (cooldown == 0)`
  - `Engine(rules, players: list[tuple[str,str]], seed, match_id="local", map_data: MapData | None = None, max_missed_turns: int = 4)`；`players` 的每个元素是 `(name, kind)`，玩家 ID 由引擎按顺序分配为 `P1..Pn`
  - `Engine.turn: int`，`Engine.finished: bool`，`Engine.turn_limit`，`Engine.nodes: list[Node]`
  - `Engine.validate_action(player_id: str, action: dict, turn: int) -> dict`
  - `Engine.resolve(actions: dict[str, dict]) -> list[dict]`
  - `Engine.state_payload(for_player: str | None = None) -> dict`
  - `Engine.start_payload(for_player: str | None = None) -> dict`（含 `match_id,seed,turn_limit,rules,arena,players,you?`）
  - `Engine.players: dict[str, Player]`（测试可直接设置位置）

- [ ] **Step 1: 写失败测试（移动与校验）**

```python
# server/tests/test_movement.py
import unittest
from arena_server.config import Rules
from arena_server.engine import ActionError, Engine, MapData, NODE_POINTS


def open_engine(n=2):
    m = MapData(15, 15, frozenset(), NODE_POINTS)
    e = Engine(Rules(), [(f"Bot{i}", "agent") for i in range(1, n + 1)],
               seed=1, map_data=m)
    e.players["P1"].pos = (5, 5)
    if "P2" in e.players:
        e.players["P2"].pos = (9, 5)
    return e


class MovementTests(unittest.TestCase):
    def test_move_validates_direction_and_wall(self):
        e = open_engine()
        self.assertEqual(
            e.validate_action("P1", {"type": "move", "dir": "e"}, 1),
            {"type": "move", "dir": "e"},
        )
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "move", "dir": "x"}, 1)
        self.assertEqual(ctx.exception.code, "invalid_action")
        e.players["P1"].pos = (1, 5)
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "move", "dir": "w"}, 1)
        self.assertEqual(ctx.exception.code, "wall")

    def test_move_collision_and_occupied(self):
        e = open_engine()
        e.players["P2"].pos = (7, 5)
        e.resolve({
            "P1": {"type": "move", "dir": "e"},
            "P2": {"type": "move", "dir": "e"},
        })
        self.assertEqual(e.players["P1"].pos, (6, 5))
        self.assertEqual(e.players["P2"].pos, (8, 5))
        # 回到初始，制造同目标
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (7, 5)
        e.resolve({
            "P1": {"type": "move", "dir": "e"},   # (6,5)
            "P2": {"type": "move", "dir": "w"},   # (6,5)
        })
        self.assertEqual(e.players["P1"].pos, (5, 5))
        self.assertEqual(e.players["P2"].pos, (7, 5))
        # 目标格被不移动的玩家占用
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.resolve({"P1": {"type": "move", "dir": "e"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].pos, (5, 5))

    def test_dash_blocked_by_occupied_middle_and_cost_still_paid(self):
        e = open_engine()
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.players["P1"].energy = 50
        e.resolve({"P1": {"type": "dash", "dir": "e"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].pos, (5, 5))
        self.assertEqual(e.players["P1"].energy, 50 - 18 + 4)

    def test_energy_and_dead_validation(self):
        e = open_engine()
        e.players["P1"].energy = 0
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "attack", "dir": "e"}, 1)
        self.assertEqual(ctx.exception.code, "insufficient_energy")
        e.players["P1"].alive = False
        with self.assertRaises(ActionError) as ctx:
            e.validate_action("P1", {"type": "wait"}, 1)
        self.assertEqual(ctx.exception.code, "not_alive")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 确认失败**

`cd server; python -m unittest tests.test_movement -v`
Expected: ImportError/ActionError 未定义。

- [ ] **Step 3: 实现玩家、校验、移动与 wait 结算**

实现要点（完整逻辑）：

- `DIRS = {"n":(0,-1),"e":(1,0),"s":(0,1),"w":(-1,0)}`
- `Engine.__init__`：按 `players` 顺序分配 `P1..Pn`；出生点从 `SPAWN_POINTS` 按种子随机取（2 人取对角，3 人取三角，4 人全取）；HP/能量/护盾初始化；节点 cooldown=0。
- `validate_action`：
  - 校验 `turn == self.turn`，否则 `ActionError("stale_turn", ...)`；玩家存在/存活；`action` 是 dict 且 `type` 合法。
  - `move/dash`：方向合法；目标格（dash 两格）界内且不在 `map.walls`；dash 检查能量。
  - `attack`：方向合法、能量足够。
  - `gather`：玩家当前格是激活节点。
  - `shield`：能量足够且 `shield < max_shield`。
  - `heal`：能量足够且 `hp < max_hp`。
  - 返回白名单化后的 action 字典。
- `resolve`：
  - 对所有存活玩家：有动作则 `missed_turns = 0`；无动作则视为 `wait` 且 `missed_turns += 1`（判负阈值在 Task 3 处理）。
  - 扣能量：`dash/attack/heal/shield` 的成本在移动前扣除，即使后续失败。
  - 移动意图：目标格必须初始为空（只考虑存活玩家位置）；重复目标全部失败；dash 中间格不能有玩家或成为其他移动意图的目标；dash 目标同样不能重复。成功者原子移动，事件 `move/dash`；失败事件 `blocked`。
  - `wait` 不产生事件；`gather/shield/heal/attack` 本任务先只记录，由 Task 3 补齐。
  - 结算收尾（**Task 2 就必须实现，Task 3 不得重复添加**）：
    - 所有存活玩家 `energy = min(max_energy, energy + energy_regen)`；
    - 所有 `cooldown > 0` 的节点 `cooldown -= 1`；
    - `last_events` 保存本回合事件，`events_turn = 本回合结算前的 turn`；
    - `turn += 1`（Task 3 加入结束判定后会改成“未结束才递增”）。
- `state_payload`：按规格 §5.5 输出 `turn, turn_limit, players, nodes, events_turn, events`，玩家字段包含 `kind`、`stats`；`for_player` 只负责加 `you`，不得改变公共数据。第一回合 `events=[]`、`events_turn=0`。
- `start_payload`：输出 `match_id,seed,turn_limit,rules.to_dict(),arena,players,you?`；`arena` 含 `width,height,walls,nodes,spawns`；坐标全部序列化为 `[x,y]`。

- [ ] **Step 4: 补充测试并跑通**

`cd server; python -m unittest tests.test_movement -v`
Expected: 4 tests PASS。

- [ ] **Step 5: Commit**

```powershell
git add server/arena_server/engine.py server/tests/test_movement.py
git commit -m "feat(server): validate actions and resolve simultaneous movement"
```

---

### Task 3: 战斗、资源、计分、结束时序

**Files:**
- Modify: `server/arena_server/engine.py`
- Create: `server/tests/test_combat.py`
- Create: `server/tests/test_endgame.py`

**Interfaces:**
- Produces: 完整 `Engine.resolve(actions)`；`Engine.end_payload(reason: str | None = None) -> dict`；`Engine.standings() -> list[dict]`；`Engine.forfeit(player_id)`；`Engine.finished`、`Engine.end_reason`、`Engine.completed_turns`。
- Events：规格 §5.7 全部类型。
- 结束判定：规格 §3.6。

- [ ] **Step 1: 写失败测试（战斗与资源）**

```python
# server/tests/test_combat.py
import unittest
from arena_server.config import Rules
from arena_server.engine import Engine, MapData, NODE_POINTS


def engine():
    e = Engine(Rules(), [("A", "agent"), ("B", "agent")],
               seed=2, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
    e.players["P1"].pos = (5, 5)
    e.players["P2"].pos = (6, 5)
    e.players["P1"].energy = 50
    e.players["P2"].energy = 50
    return e

class CombatTests(unittest.TestCase):
    def test_attack_uses_post_movement_position_and_shield(self):
        e = engine()
        e.players["P2"].shield = 20
        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "shield"},
        })
        self.assertEqual(e.players["P1"].energy, 50 - 8 + 4)
        self.assertEqual(e.players["P2"].energy, 50 - 12 + 4)
        # 攻击在 shield 动作生效后结算：40 吸收 22，剩余 18 护盾，HP 不变
        self.assertEqual(e.players["P2"].shield, 18)
        self.assertEqual(e.players["P2"].hp, 100)

    def test_move_out_of_range_dodges(self):
        e = engine()
        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "move", "dir": "e"},
        })
        self.assertEqual(e.players["P2"].hp, 100)
        self.assertEqual(e.players["P1"].energy, 50 - 8 + 4)

    def test_simultaneous_kill_credit(self):
        e = engine()
        e.players["P1"].hp = 10
        e.players["P2"].hp = 10
        e.resolve({
            "P1": {"type": "attack", "dir": "e"},
            "P2": {"type": "attack", "dir": "w"},
        })
        self.assertFalse(e.players["P1"].alive)
        self.assertFalse(e.players["P2"].alive)
        self.assertEqual(e.players["P1"].kills, 1)
        self.assertEqual(e.players["P2"].kills, 1)

    def test_gather_and_node_cooldown(self):
        e = engine()
        e.players["P1"].pos = (7, 7)
        e.players["P1"].energy = 50
        e.resolve({"P1": {"type": "gather"}, "P2": {"type": "wait"}})
        self.assertEqual(e.players["P1"].energy, 80 + 4)  # 50 + 30 + regen
        self.assertEqual(e.players["P1"].score, 10)
        node = next(n for n in e.nodes if n.pos == (7, 7))
        self.assertEqual(node.cooldown, 3)  # 4 设置后本回合 -1
```

```python
# server/tests/test_endgame.py
import unittest
from arena_server.config import Rules
from arena_server.engine import Engine, MapData, NODE_POINTS

class EndgameTests(unittest.TestCase):
    def make(self, limit=2):
        e = Engine(Rules(turn_limit=limit), [("A", "agent"), ("B", "agent")],
                   seed=3, map_data=MapData(15, 15, frozenset(), NODE_POINTS))
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (9, 9)
        return e

    def test_turn_limit_winner(self):
        e = self.make(1)
        e.players["P1"].score = 5
        e.resolve({"P1": {"type": "wait"}, "P2": {"type": "wait"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_payload()["reason"], "turn_limit")
        self.assertEqual(e.end_payload()["winner"]["id"], "P1")

    def test_mutual_destruction(self):
        e = self.make(5)
        e.players["P1"].pos, e.players["P2"].pos = (5, 5), (6, 5)
        e.players["P1"].hp = e.players["P2"].hp = 5
        e.players["P1"].energy = e.players["P2"].energy = 50
        e.resolve({"P1": {"type": "attack", "dir": "e"},
                   "P2": {"type": "attack", "dir": "w"}})
        self.assertTrue(e.finished)
        self.assertEqual(e.end_payload()["reason"], "mutual_destruction")
        self.assertIsNotNone(e.end_payload()["winner"])

    def test_forfeit(self):
        e = self.make(5)
        e.forfeit("P2")
        self.assertTrue(e.finished)
        self.assertEqual(e.players["P1"].alive, True)
        self.assertEqual(e.end_payload()["reason"], "last_standing")
```

- [ ] **Step 2: 确认失败**

`cd server; python -m unittest tests.test_combat tests.test_endgame -v`
Expected: FAIL（战斗/结束逻辑未实现）。

- [ ] **Step 3: 实现结算**

按规格 §3.4 的顺序实现（Task 2 已实现移动、能量恢复、节点冷却，不要重复添加）：

1. 锁定动作，补 wait，连续漏操作 +1；提交者归零。
2. 扣能量（Task 2 已有）。
3. 移动（Task 2 已有）。
4. 护盾/治疗/采集：护盾先加；采集节点设 `cooldown=4`，得分/能量；仅在提交时校验；应用上限。
5. 战斗：对每个存活玩家（本回合开始时 alive）的 attack，用移动后位置找目标；护盾吸收；累计 HP 伤害；记录 `attack/damage` 事件；所有攻击结算完再判死。
6. 死亡：`hp<=0` → alive=False、事件 `death`；击杀归属为该目标本回合 HP 伤害最高者，并列 ID 升序，+25 分。
7. 连续漏操作达到 `max_missed_turns`（默认 4）→ `forfeit` 事件、alive=False、hp=0、forfeited=True；无击杀者。
8. 检查结束：在 `resolve` 开头保存 `current_turn = self.turn`；本回合所有效果与死亡判定完成后设置 `completed_turns = current_turn`，再按顺序检查：0 存活 `mutual_destruction`；1 存活 `last_standing`；`completed_turns >= turn_limit` 且还有 ≥2 存活 `turn_limit`。仅当未结束时 `self.turn = current_turn + 1`；结束时 `self.turn` 保持 `current_turn`。

`end_payload`：按排名规则输出 `standings`；winner 规则见规格 §3.6；包含最后一回合 events、`events_turn`、`turns=completed_turns`。

- [ ] **Step 4: 补充边界测试**

至少覆盖：

- 护盾溢出到 HP、护盾伤害不计分。
- 治疗上限、护盾上限、能量上限。
- 攻击空位仍扣能量。
- 击杀并列按 ID。
- 连续 4 次未提交判负。
- 排名按存活→分数→HP→能量→ID。
- 最后一回合结束不再增加 turn。

- [ ] **Step 5: 跑全部 server 引擎测试**

`cd server; python -m unittest discover -s tests -p "test_*.py" -v`
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```powershell
git add server/arena_server/engine.py server/tests/test_combat.py server/tests/test_endgame.py
git commit -m "feat(server): resolve combat, resources, scoring and end conditions"
```

---

### Task 4: 协议、参与者、大厅、单局循环与 TCP 网关

**Files:**
- Create: `server/arena_server/protocol.py`
- Create: `server/arena_server/participants.py`
- Create: `server/arena_server/lobby.py`
- Create: `server/arena_server/match.py`
- Create: `server/arena_server/logging_utils.py`
- Create: `server/arena_server/tcp_gateway.py`
- Create: `server/arena_server/server.py`
- Create: `server/arena_server/__main__.py`
- Create: `server/tests/test_tcp.py`

**Interfaces:**
- Produces:
  - `PROTOCOL = 1`, `make_error(code, message, turn=None) -> dict`, `ServerFull(Exception)`
  - `Participant` 字段：`name, kind, transport, player_id, state, missed_turns, tcp, session, joined_at`；`@dataclass(eq=False)` 保证可哈希
  - `Lobby.add(p)`, `Lobby.remove(p)`, `Lobby.take(n)`, `Lobby.snapshot() -> dict`
  - `Match(engine, participants, server, tick_ms, min_turn_ms, log, on_end)`；`await match.run()`；`match.submit(participant, turn, action) -> dict`；`await match.forfeit(participant, reason="forfeit")`；`match.view_for(participant) -> dict`；`match.snapshot_for_spectator() -> tuple[dict, dict]`
  - `GameServer(config)`；`await start() -> tuple[int, int | None]`（本任务第二个值为 `None`，Task 5 改为真实 HTTP 端口）；`await stop()`；`await run_forever()`
  - `GameServer.send(participant, msg)`、`GameServer.broadcast_spectators(msg)`、`GameServer.add_to_lobby(p)`、`GameServer.remove_participant(p)`、`GameServer.lobby_view()`、`GameServer.client_count()`；`GameServer.spectators: set`、`GameServer.match: Match | None`
  - `MatchLog(path)` / `NullLog`，方法 `write(msg)`、`close()`

- [ ] **Step 1: 写失败集成测试（TCP）**

```python
# server/tests/test_tcp.py
import asyncio
import json
import unittest
from arena_server.config import ServerConfig
from arena_server.server import GameServer


class TcpHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = GameServer(ServerConfig(
            host="127.0.0.1", tcp_port=0, api_port=0,
            tick_ms=500, min_turn_ms=0, turn_limit=3,
            lobby_wait_ms=20, seed=11, no_logs=True,
        ))
        self.tcp_port, self.api_port = await self.server.start()
        self.assertIsNone(self.api_port, "Task 4 must not start HTTP yet")
        self.writers = []

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        await self.server.stop()

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)
        self.writers.append(writer)
        welcome = await self.read_json(reader)
        self.assertEqual(welcome["type"], "welcome")
        return reader, writer

    async def send(self, writer, msg):
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()

    async def read_json(self, reader, timeout=5):
        line = await asyncio.wait_for(reader.readline(), timeout)
        self.assertTrue(line, "connection closed")
        return json.loads(line)

    async def read_until(self, reader, wanted, timeout=5):
        wanted = {wanted} if isinstance(wanted, str) else set(wanted)
        while True:
            msg = await self.read_json(reader, timeout)
            if msg["type"] in wanted:
                return msg

    async def join(self, reader, writer, name):
        await self.send(writer, {"type": "join", "protocol": 1, "name": name})
        return await self.read_until(reader, "start")

    async def play_waits(self, reader, writer):
        last_turn = -1
        while True:
            msg = await self.read_json(reader)
            if msg["type"] == "state" and msg["turn"] != last_turn:
                last_turn = msg["turn"]
                me = next(p for p in msg["players"] if p["id"] == msg["you"])
                if me["alive"]:
                    await self.send(writer, {
                        "type": "action", "turn": msg["turn"],
                        "action": {"type": "wait"},
                    })
            if msg["type"] == "end":
                return msg

    async def test_two_agents_lobby_match_and_end(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        lobbies = []

        async def collect(reader, writer, name):
            await self.send(writer, {"type": "join", "protocol": 1, "name": name})
            while True:
                msg = await self.read_json(reader)
                if msg["type"] == "lobby":
                    lobbies.append(msg)
                if msg["type"] == "start":
                    return msg

        start1, start2 = await asyncio.gather(
            collect(r1, w1, "A"), collect(r2, w2, "B"),
        )
        self.assertEqual(start1["you"], "P1")
        self.assertEqual(start2["you"], "P2")
        self.assertEqual(start1["players"][0]["kind"], "agent")
        self.assertTrue(lobbies, "no lobby broadcast observed")
        self.assertEqual({p["name"] for p in lobbies[-1]["players"]}, {"A", "B"})

        end1, end2 = await asyncio.gather(
            self.play_waits(r1, w1), self.play_waits(r2, w2),
        )
        self.assertEqual(end1["reason"], "turn_limit")
        self.assertEqual(end1["match_id"], end2["match_id"])
        self.assertEqual(len(end1["standings"]), 2)

    async def test_spectator_gets_start_and_state_snapshot(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        await asyncio.gather(
            self.join(r1, w1, "A"), self.join(r2, w2, "B"),
        )
        rs, ws = await self.connect()
        await self.send(ws, {"type": "spectate"})
        msg = await self.read_until(rs, "spectating")
        self.assertTrue(msg["match_running"])
        start = await self.read_until(rs, "start")
        self.assertNotIn("you", start)
        state = await self.read_until(rs, "state")
        self.assertNotIn("you", state)
        self.assertGreaterEqual(state["turn"], 1)

    async def test_disconnect_forfeits_and_ends_match(self):
        r1, w1 = await self.connect()
        r2, w2 = await self.connect()
        await asyncio.gather(
            self.join(r1, w1, "A"), self.join(r2, w2, "B"),
        )
        w2.close()
        end = await self.read_until(r1, "end", timeout=5)
        self.assertEqual(end["reason"], "last_standing")
        self.assertEqual(end["winner"]["id"], "P1")
```

- [ ] **Step 2: 确认失败**

`cd server; python -m unittest tests.test_tcp -v`
Expected: ImportError（GameServer 未定义）。

- [ ] **Step 3: 实现协议与参与者**

- `protocol.py`：`PROTOCOL=1`；`make_error(code, message, turn=None)` 返回带 `type=error` 的字典；`ServerFull(Exception)` 供大厅/连接上限使用；`validate_name(raw) -> str` 去除首尾空白、拒绝空/超过 20 字符/控制字符；`ActionError` 从 `engine` 导入并复用。
- `participants.py`：`@dataclass(eq=False) Participant`，字段 `name, kind, transport, player_id=None, state="lobby", missed_turns=0, tcp=None, session=None, match=None, joined_at=time.monotonic()`；`eq=False` 保证可哈希、可放进集合。
- 名字唯一化：对当前大厅 + 当前比赛 + 观战者名单做大小写无关去重，依次尝试 `name`、`name-2`、`name-3`；最终名字写入 `participant.name`。
- `Participant` 不持有游戏数值；HP/能量等全部在 `Engine.Player` 中。TCP 连接对象只需提供 `async send(msg)` 和 `close()`。

- [ ] **Step 4: 实现大厅与 Match**

- `Lobby`：`waiting: list[Participant]`；`deadline: float | None`；`add/remove` 返回列表是否变化；`take(n)` 取队头至多 n 人；`snapshot()` 返回 `players, min_players, max_players, starts_in_ms`（不足 2 人时 `starts_in_ms=None`，用 `max(0, int((deadline-now)*1000))`）。
- `Match.__init__` 保存 `engine, participants, server, tick_ms, min_turn_ms, log, on_end`；`pending: dict[str, dict]`、`ready: asyncio.Event`、`closed=False`、`start_payloads: dict[str, dict]`、`current_views: dict[str, dict]`、`last_events`。
- `Match.run()`：
  1. 为每个参赛者生成 `start_payload(you)` 并发送；同时向观战者发送无 `you` 的 start。
  2. 每回合：清空 `pending`、`ready`、`closed=False`；`turn = engine.turn`；为每个参赛者生成 state（`state_payload(pid)` + `match_id/tick_ms/reply_by_ms`，`reply_by_ms = int(time.time()*1000) + tick_ms`），发送并保存到 `current_views`；观战者收到无 `you` 的 state。
  3. 等待：循环直到 `engine.finished` 或所有存活参赛者都在 `pending` 中或到达 `deadline`；用 `asyncio.wait_for(self.ready.wait(), remaining)` 唤醒；`submit` 在凑齐全员时 `ready.set()`。
  4. 全员提前提交时 `await asyncio.sleep(min_turn_ms/1000)`；若 `engine.finished` 则跳过。
  5. `closed=True`；取出 `actions`（未提交者不传，引擎按 wait 处理）；`events = engine.resolve(actions)`；写入日志；若 `engine.finished` 退出循环。
  6. 循环结束后生成 `end_payload`，发送给参赛者与观战者，`log.write(end)`，`log.close()`，`await on_end(self)`；异常时构造 `reason="aborted"` 的 end，记录堆栈并同样回调。
- 每回合 `engine.resolve` 之后、发送下一回合 state 之前，用结算后的 `engine.state_payload(pid)`、`turn=engine.completed_turns`、`events=engine.last_events`、`events_turn=engine.completed_turns` 重建 `current_views`；这样 HTTP `ended` 视图拿到的是最终棋盘，而不是结算前快照。
- `Match.submit(participant, turn, action)`：
  - 不在 `participants` → `ActionError("not_in_match")`；`closed` 或 `engine.finished` → `turn_closed`；`turn != engine.turn` → `stale_turn`；
  - `engine.validate_action(participant.player_id, action, turn)`；成功写入 `pending`；当所有存活参赛者都有 pending 时 `ready.set()`；返回规范化 action。
- `Match.forfeit(participant, reason="forfeit")`：调用 `engine.forfeit(player_id)`，写事件到 `last_events`，`ready.set()`；重复调用幂等。断线、HTTP DELETE、`leave` 都走这里。
- `Match.view_for(participant)`：把 `start_payloads[player_id]` 中的 `seed, turn_limit, rules, arena` 与 `current_views[player_id]` 的回合状态合并，再追加 `submitted`（该玩家是否有 pending）和 `your_action`；若已结束使用最后一份 state。不得在 HTTP 视图中缺少地图或规则。
- `Match.snapshot_for_spectator()`：返回 `(start_no_you, current_state_no_you)`；没有 state 时用 `engine.state_payload(None)` 生成。
- HTTP 与 TCP 都使用同一个 `submit`；发送由 `GameServer.send(participant, msg)` 与 `broadcast_spectators(msg)` 决定，Match 不直接操作 socket。

- [ ] **Step 5: 实现 TCP 网关**

- `asyncio.start_server(..., limit=65536)`；每连接先发 `welcome`（`server, protocol, client_id`）。
- 每连接一个读循环 + 一个写协程；写协程消费 `asyncio.Queue`，保证 NDJSON 行完整。读循环用 `reader.readline()`，超长行直接关闭。
- 消息路由：
  - `join`：校验 protocol/name；重复 join → `already_joined`；创建 `Participant(kind="agent", transport="tcp", tcp=conn)`；`await server.add_to_lobby(p)`；发送 `joined`；广播大厅。
  - `spectate`：加入 `server.spectators`；发送 `spectating`；若比赛进行中，发送 `match.snapshot_for_spectator()`；否则等待大厅广播。
  - `action`：必须已 join 且 `participant.match` 存在；调用 `match.submit`；成功发送 `action_ack`；`ActionError` 发送 `error`（带 `turn`）。
  - `leave`：大厅中移除；比赛中 `await match.forfeit(...)`；发送 `left`；连接保持，可再次 join。
  - `ping`：回 `pong` 并回显 `ts`。
  - 未知类型：`invalid_message`，不断开。
- 限流：每连接 30 条/秒令牌桶；超限 `rate_limited`，不关闭连接。
- 连接数上限：`server.client_count() >= max_clients` 时发送 `server_full` 并关闭。
- 断线清理：从大厅/观战者移除；若在比赛中调用 `match.forfeit`；关闭写协程。
- 观战中途接入：发送 `spectating` 后立即补 `start`（无 `you`）+ 当前 `state`。

- [ ] **Step 6: 实现 GameServer 与 CLI**

- `GameServer.start()`：只启动 TCP，返回 `(self.tcp_port, None)`；Task 5 再把第二个值改为 HTTP 端口并启动 HTTP。启动日志打印 `Agent TCP : host:port`。
- `GameServer._lobby_loop()`：每 50ms 检查；`self.match is None and len(waiting) >= min_players` 且无 deadline → `deadline = now + lobby_wait_ms/1000` 并广播；`< min_players` → 清空 deadline；`>= max_players` → 立即开赛；deadline 到期 → 开赛。大厅快照变化/倒计时整秒变化时广播。
- `GameServer._start_match()`：若 `self.match` 仍在运行则直接返回；从 Lobby `take(min(max_players, len(waiting)))`；按顺序分配 `P1..Pn`；设置 `participant.state="playing"` 与 `participant.match`；`seed = config.seed + match_index`（未配置则 `random.randrange(2**31)`）；`match_id = "m-YYYYMMDD-HHMMSS-" + 4 位十六进制`；`engine = Engine(config.rules(), [(p.name, p.kind)], seed, match_id, max_missed_turns=config.max_missed_turns)`；创建日志（`no_logs` 用 NullLog）；`asyncio.create_task(match.run())`。
- `GameServer.send(participant, msg)`：transport 为 tcp → `await participant.tcp.send(msg)`；http → 仅更新该参与者的 `current_views`（HTTP 靠轮询取视图，不推送）。
- `GameServer.broadcast_spectators(msg)`：遍历 `self.spectators` 发送；异常连接移除。
- `GameServer.add_to_lobby(p)`：`p.state="lobby"`，`lobby.add(p)`，广播大厅；满员抛 `ServerFull`（由 TCP/HTTP 层转成 `server_full`）。
- `GameServer.remove_participant(p)`：大厅中 `lobby.remove`；比赛中 `await p.match.forfeit(p)`；完成后 `p.state="idle"`、`p.match=None`；广播大厅。
- `on_end`：把参赛者设为 `idle`、清空 `match`；HTTP 会话保留 ended 视图（Task 5 填充）；关闭日志；广播大厅；不自动重新排队。
- `GameServer.stop()`：取消大厅循环、会话清理循环（Task 5）与当前 Match 任务；关闭 TCP server 与所有连接；等待任务结束；幂等。
- `__main__.py`：`argparse` 解析 `--host/--tcp-port/--api-port/--tick-ms/--min-turn-ms/--turn-limit/--min-players/--max-players/--lobby-wait-ms/--seed/--no-logs/--log-dir/--max-missed-turns/--max-clients/--cors-origin/--verbose/--version`，构造 `ServerConfig`，`asyncio.run(GameServer(config).run_forever())`；`KeyboardInterrupt` 优雅停止。
- 运行中异常：`run_forever` 捕获 `CancelledError` 正常退出；端口占用直接打印错误并以非零码退出。

- [ ] **Step 7: 跑测试**

`cd server; python -m unittest tests.test_tcp -v`
Expected: 3 tests PASS（若超时，先修计时/唤醒逻辑，不放宽测试掩盖问题）。

- [ ] **Step 8: Commit**

```powershell
git add server/arena_server server/tests/test_tcp.py
git commit -m "feat(server): add lobby, match loop and TCP agent gateway"
```

---

### Task 5: HTTP API、会话与人类/Agent 混合对局

**Files:**
- Create: `server/arena_server/sessions.py`
- Create: `server/arena_server/http_api.py`
- Modify: `server/arena_server/server.py`
- Create: `server/tests/test_http_api.py`

**Interfaces:**
- Produces:
  - `Session`：`token, participant, created_at, last_poll, requests: deque, ended_result=None, ended_match=None, ended_at=None`
  - `SessionManager.create(participant) -> Session`、`get(token) -> Session | None`、`drop(token)`、`cleanup(now) -> list[Session]`；token 用 `secrets.token_urlsafe(24)`
  - `HttpApi(server, config)`；`await start() -> int`；`await stop()`
  - `GameServer.sessions`、`GameServer.create_human(name) -> tuple[Session, Participant]`、`GameServer.requeue(participant)`、`GameServer.view_for(participant) -> dict`、`GameServer.health_payload() -> dict`、`GameServer.rules_payload() -> dict`
  - `GameServer.start() -> tuple[int, int]`（本任务起第二个值为真实 HTTP 端口）

- [ ] **Step 1: 写失败集成测试（HTTP + 混合）**

```python
# server/tests/test_http_api.py
import asyncio
import json
import unittest
import urllib.error
import urllib.request
from arena_server.config import ServerConfig
from arena_server.server import GameServer


class HttpHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = GameServer(ServerConfig(
            host="127.0.0.1", tcp_port=0, api_port=0,
            tick_ms=400, min_turn_ms=0, turn_limit=2,
            lobby_wait_ms=30, seed=5, no_logs=True,
        ))
        self.tcp_port, self.api_port = await self.server.start()
        self.base = f"http://127.0.0.1:{self.api_port}/api/v1"

    async def asyncTearDown(self):
        await self.server.stop()

    def _request(self, method, path, body=None, token=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=headers or {})
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                payload = json.loads(resp.read() or b"{}")
                return resp.status, payload, {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            payload = json.loads(raw) if raw else {}
            return exc.code, payload, {k.lower(): v for k, v in exc.headers.items()}

    async def request(self, method, path, **kwargs):
        return await asyncio.to_thread(self._request, method, path, **kwargs)

    async def create_session(self, name):
        status, data, _ = await self.request("POST", "/sessions", body={"name": name})
        self.assertEqual(status, 200, data)
        return data["token"], data["view"]

    async def test_health_rules_cors_and_unknown_path(self):
        status, data, headers = await self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["protocol"], 1)
        self.assertEqual(headers["access-control-allow-origin"], "*")

        status, data, _ = await self.request("GET", "/rules")
        self.assertEqual(status, 200)
        self.assertIn("attack", data["rules"])

        status, data, _ = await self.request("GET", "/")
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])

        status, _, headers = await self.request(
            "OPTIONS", "/sessions",
            headers={"Origin": "http://127.0.0.1:8090",
                     "Access-Control-Request-Method": "POST"},
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers["access-control-allow-origin"], "*")

    async def test_session_auth_state_and_delete(self):
        token, view = await self.create_session("Alice")
        self.assertEqual(view["mode"], "lobby")
        self.assertEqual(view["you"]["name"], "Alice")
        self.assertIsNone(view["you"]["id"])

        status, data, _ = await self.request("GET", "/state")
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "unauthorized")

        status, data, _ = await self.request("GET", "/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["view"]["mode"], "lobby")

        status, data, _ = await self.request("DELETE", "/sessions", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        status, _, _ = await self.request("GET", "/state", token=token)
        self.assertEqual(status, 401)

    async def test_mixed_tcp_agent_and_http_human_finish_match(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)
        welcome = json.loads(await asyncio.wait_for(reader.readline(), 3))
        self.assertEqual(welcome["type"], "welcome")
        writer.write((json.dumps({"type": "join", "protocol": 1,
                                  "name": "Agent-A"}) + "\n").encode())
        await writer.drain()

        token, view = await self.create_session("Human-H")

        async def drive_agent():
            last_turn = -1
            while True:
                line = await asyncio.wait_for(reader.readline(), 5)
                self.assertTrue(line, "agent connection closed")
                msg = json.loads(line)
                if msg["type"] == "state" and msg["turn"] != last_turn:
                    last_turn = msg["turn"]
                    writer.write((json.dumps({
                        "type": "action", "turn": msg["turn"],
                        "action": {"type": "wait"},
                    }) + "\n").encode())
                    await writer.drain()
                if msg["type"] == "end":
                    return msg

        agent_task = asyncio.create_task(drive_agent())
        final_view = None
        deadline = asyncio.get_running_loop().time() + 20
        while asyncio.get_running_loop().time() < deadline:
            status, data, _ = await self.request("GET", "/state", token=token)
            self.assertEqual(status, 200, data)
            final_view = data["view"]
            if final_view["mode"] == "match":
                match = final_view["match"]
                self.assertEqual({p["kind"] for p in match["players"]},
                                 {"agent", "human"})
                if not match["submitted"]:
                    await self.request("POST", "/actions", token=token, body={
                        "turn": match["turn"], "action": {"type": "wait"},
                    })
            elif final_view["mode"] == "ended":
                break
            await asyncio.sleep(0.05)

        self.assertIsNotNone(final_view)
        self.assertEqual(final_view["mode"], "ended")
        self.assertIn(final_view["result"]["reason"],
                      {"last_standing", "turn_limit", "mutual_destruction"})
        self.assertEqual(len(final_view["result"]["standings"]), 2)
        end = await asyncio.wait_for(agent_task, 5)
        self.assertEqual(end["match_id"], final_view["result"]["match_id"])
        writer.close()
        await writer.wait_closed()
```

- [ ] **Step 2: 确认失败**

`cd server; python -m unittest tests.test_http_api -v`
Expected: ImportError（HttpApi 未实现）或连接失败。

- [ ] **Step 3: 实现 SessionManager**

- `token = secrets.token_urlsafe(24)`；`last_poll = time.monotonic()`；`requests` 用 `collections.deque` 保存最近 1 秒的请求时间。
- `cleanup(now)` 返回需要删除的会话：
  - `participant.state == "lobby"` 且 `now - last_poll > 30`；
  - `ended_result` 存在且 `now - ended_at > 600`。
- 删除时由 `GameServer` 调用 `lobby.remove`/`drop`，并清空 `participant.session`；不得在 SessionManager 里直接改游戏状态。

- [ ] **Step 4: 实现 HttpApi**

- 独立 `asyncio.start_server`，每请求短连接；手写解析请求行/头/`Content-Length` body；限制请求头 16 KiB、body 32 KiB；不支持 chunked；超限返回 413/431 并关闭。
- 响应统一 `{"ok": true, ...}` / `{"ok": false, "error": {"code","message"}}`；`Content-Type: application/json; charset=utf-8`；`Connection: close`；所有响应（含错误、OPTIONS、404）都带 CORS 头。`config.cors_origin == "*"` 时返回 `*`；否则仅当请求 `Origin` 在逗号分隔白名单内时回显该 Origin，不回显 `*`。
- 路由：
  - `GET /api/v1/health`、`GET /api/v1/rules`：无需 token。
  - `POST /api/v1/sessions`：无 token + `name` 创建；有效 token 幂等返回；有效 token 且会话 `idle/ended` 重新排队；非法 token + 无 name → 401。
  - `GET /api/v1/state`：必须 token；更新 `last_poll`。
  - `POST /api/v1/actions`：必须 token；body `{turn, action}`；调用 `participant.match.submit(participant, turn, action)`；错误映射见下。
  - `DELETE /api/v1/sessions`：必须 token；大厅移除或比赛 forfeit；`sessions.drop`；返回 `{"ok": true}`。
  - `OPTIONS`：204；`GET /` 与未知路径：404 JSON；不提供任何静态文件。
- 鉴权：只接受 `Authorization: Bearer <token>`；缺失/无效 401 `unauthorized`；不得在日志中记录该头。
- 频率：每会话 20 请求/秒（含 state 轮询）；超过 429 `rate_limited`。
- 错误映射：`stale_turn/turn_closed/not_in_match/not_alive` → 409；`invalid_json/invalid_name/invalid_action/insufficient_energy/wall/out_of_bounds/no_active_node/full_hp/shield_full` → 400；`server_full` → 503；其它 → 500（记录堆栈，不返回内部细节）。
- `POST /sessions` 创建人类参与者：`Participant(kind="human", transport="http")`，`participant.session = session`，`await server.add_to_lobby(participant)`；返回 token + `server.view_for(participant)`。
- `view_for` 的 match 部分必须包含：`match_id, seed, turn, turn_limit, tick_ms, reply_by_ms, rules, arena, players, nodes, events_turn, events, submitted, your_action`；ended 部分包含 `result` 和冻结的 `match`。
- 服务端 404/405 不返回 HTML；任何路径都不读取 `client/`。

- [ ] **Step 5: 修改 GameServer 接入 HTTP**

- `start()`：启动 TCP 后调用 `self.http = HttpApi(self, config)`，`self.api_port = await self.http.start()`，返回 `(tcp_port, api_port)`；启动日志增加 `HTTP API  : http://host:port/api/v1`。
- `stop()`：先 `await self.http.stop()`，再关闭 TCP、取消大厅循环、关闭日志。
- `health_payload()`：`ok, server, version, protocol, uptime_s, lobby_players, match_running, active_players, spectators`。
- `rules_payload()`：`ok, protocol, rules=config.rules().to_dict(), defaults={tick_ms,min_turn_ms,turn_limit,min_players,max_players}`。
- `create_human(name)`：检查 `client_count() >= max_clients` → `ServerFull`；唯一化名字；创建 Participant；`sessions.create`；`add_to_lobby`；返回 `(session, participant)`。
- `requeue(participant)`：仅在 `idle` 时允许；清空 session 的 ended 字段；`participant.player_id=None`、`state="lobby"`、`match=None`；重新加入大厅；返回 `view_for`。
- `on_end`：对每个 HTTP 参赛者，若 `participant.session` 仍存在，保存 `ended_match = match.view_for(participant)`（最后一回合）与 `ended_result = end`，`ended_at = time.monotonic()`；TCP 参赛者不保存。
- `_session_cleanup_loop()`：每 5 秒 `sessions.cleanup(now)`；对过期会话调用 `remove_participant` 并在大厅/比赛中清理。
- `client_count()`：TCP 连接数 + 活跃会话数；用于 `server_full`。
- 测试要求：`api_port=0` 时返回真实系统端口；`/` 返回 404 JSON；`OPTIONS` 带 CORS。

- [ ] **Step 6: 跑测试**

`cd server; python -m unittest tests.test_http_api tests.test_tcp -v`
Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```powershell
git add server/arena_server/server.py server/arena_server/sessions.py server/arena_server/http_api.py server/tests/test_http_api.py
git commit -m "feat(server): add HTTP API, human sessions and mixed matches"
```

### Task 6: Agent SDK、示例 Bot 与终端观战

**Files:**
- Create: `agents/arena_agent/__init__.py`
- Create: `agents/arena_agent/protocol.py`
- Create: `agents/arena_agent/client.py`
- Create: `agents/arena_agent/policy.py`
- Create: `agents/arena_agent/pathfinding.py`
- Create: `agents/arena_agent/render.py`
- Create: `agents/bots/__init__.py`
- Create: `agents/bots/heuristic.py`
- Create: `agents/bots/random_bot.py`
- Create: `agents/bots/llm_agent.py`
- Create: `agents/tools/__init__.py`
- Create: `agents/tools/spectator.py`
- Create: `agents/tests/__init__.py`
- Create: `agents/tests/test_protocol.py`
- Create: `agents/tests/test_pathfinding.py`
- Create: `agents/tests/test_client.py`
- Create: `agents/tests/test_llm.py`
- Create: `agents/README.md`

**Interfaces:**
- Produces:
  - `PROTOCOL=1`、`DIRS`、`encode(msg)->bytes`、`decode(line)->dict`
  - `Policy` 基类：`on_lobby(lobby)`、`on_start(start)`、`decide(state)->dict|None`、`on_end(end)`、`on_error(error)`
  - `ArenaClient(host, port, name, policy, requeue=False, logger=print)`；`run()`
  - `run_agent(host, port, name, policy, requeue=False)`
  - `bfs_next_step(start, goal, walls, occupied, width=15, height=15) -> str | None`；`adjacent_dir(a,b) -> str | None`
  - `render_board(start, state, color=True) -> str`
  - 三个 Bot CLI 与 `tools.spectator` CLI

- [ ] **Step 1: 写失败测试**

```python
# agents/tests/test_protocol.py
import unittest
from arena_agent.protocol import PROTOCOL, decode, encode


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        msg = {"type": "join", "protocol": PROTOCOL, "name": "A"}
        self.assertEqual(decode(encode(msg)), msg)

    def test_reject_bad_json(self):
        with self.assertRaises(ValueError):
            decode(b"{not json}")
```

```python
# agents/tests/test_pathfinding.py
import unittest
from arena_agent.pathfinding import bfs_next_step, adjacent_dir


class PathTests(unittest.TestCase):
    def test_direct_and_blocked(self):
        self.assertEqual(bfs_next_step((1, 1), (1, 4), set(), set()), "s")
        # 目标被四面墙围住，无法到达
        enclosed = {(4, 5), (6, 5), (5, 4), (5, 6)}
        self.assertIsNone(bfs_next_step((1, 1), (5, 5), enclosed, set()))

    def test_no_path_returns_none(self):
        walls = {(0, 1), (1, 0), (2, 1), (1, 2)}
        self.assertIsNone(bfs_next_step((1, 1), (5, 5), walls, set()))

    def test_adjacent_direction(self):
        self.assertEqual(adjacent_dir((2, 2), (2, 1)), "n")
        self.assertIsNone(adjacent_dir((2, 2), (3, 3)))
```

```python
# agents/tests/test_client.py
import unittest
from arena_agent.client import ArenaClient
from arena_agent.policy import Policy


class RecordingPolicy(Policy):
    def __init__(self):
        self.calls = []

    def on_start(self, start):
        self.calls.append("start")

    def decide(self, state):
        self.calls.append("state")
        return {"type": "wait"}

    def on_end(self, end):
        self.calls.append("end")


class ClientTests(unittest.TestCase):
    def test_callback_order_and_send(self):
        policy = RecordingPolicy()
        client = ArenaClient("127.0.0.1", 1, "A", policy, logger=lambda *_: None)
        sent = []
        for msg in (
            {"type": "start", "you": "P1", "rules": {}, "players": []},
            {"type": "state", "turn": 1, "you": "P1", "players": [
                {"id": "P1", "alive": True}]},
            {"type": "end", "reason": "turn_limit"},
        ):
            client.handle(msg, sent.append)
        self.assertEqual(policy.calls, ["start", "state", "end"])
        self.assertEqual(sent, [{"type": "action", "turn": 1,
                                "action": {"type": "wait"}}])
```

```python
# agents/tests/test_llm.py
import unittest
from bots.llm_agent import parse_action


class LlmTests(unittest.TestCase):
    def test_extract_json_action(self):
        text = 'thinking... {"type": "attack", "dir": "e"} done'
        self.assertEqual(parse_action(text), {"type": "attack", "dir": "e"})

    def test_reject_non_action(self):
        self.assertIsNone(parse_action("I will attack"))
        self.assertIsNone(parse_action('{"type": "fly"}'))
```

- [ ] **Step 2: 确认失败**

`cd agents; python -m unittest discover -s tests -v`
Expected: ImportError（`arena_agent` 模块未实现）。

- [ ] **Step 3: 实现 SDK**

- `protocol.py`：`encode` 用 `json.dumps(..., ensure_ascii=False, separators=(",", ":")) + "\n"` 编码为 UTF-8；`decode` 校验 UTF-8/JSON object/`type` 字段；`DIRS = {"n":(0,-1),"e":(1,0),"s":(0,1),"w":(-1,0)}`。
- `pathfinding.py`：BFS 四邻域，跳过墙与占用格；返回从 `start` 迈出的第一步方向；起点等于终点返回 `None`；`adjacent_dir` 返回相邻方向或 `None`。
- `policy.py`：`Policy` 默认 `decide` 返回 `{"type":"wait"}`；`safe_decide(policy, state)` 捕获异常并返回 wait，打印异常类型。
- `client.py`：
  - `run()`：连接失败按 1s/2s/4s（上限 8s）退避；`requeue=True` 时对局结束后 sleep 1s 重连，默认结束退出。
  - `_run_once()`：`socket.create_connection((host, port), timeout=10)`；`makefile("rwb")`；读取 `welcome` 校验 `protocol == 1`；发送 `{"type":"join","protocol":1,"name":name}`；循环读行。
  - `handle(msg, send)`（单独方法，便于测试）：
    - `lobby` → `policy.on_lobby`；`start` → 记录 `self.player_id=start.get("you")`、`self.start_payload`，`policy.on_start`；
    - `state` → 找 `you` 对应玩家；若 `alive`，`action = safe_decide(...)`；若 action 非空，`send({"type":"action","turn":state["turn"],"action":action})`；
    - `end` → `policy.on_end`；返回 `False` 表示结束；
    - `error` → `policy.on_error`；`joined`/`spectating`/`pong` 忽略；未知类型忽略。
  - `_send` 写入并 flush；连接关闭/超时抛 `ConnectionError`。
- `render.py`：15×15 ASCII 网格；墙 `#`；玩家取名字首字母（同字母冲突用 P1..P4）；节点 `*` 激活、`o` 冷却；状态行含回合、HP/能量/护盾/分数；`color=False` 时无 ANSI。

- [ ] **Step 4: 实现三个 Bot**

- `random_bot.py`：`RandomPolicy.decide` 收集本地合法动作：`wait`；四方向 `move`；能量足够时 `dash/attack`；站在激活节点上 `gather`；护盾/治疗未满且能量足够；用 `random.Random(zlib.crc32(name.encode("utf-8")))` 选题（不用内置 `hash()`，避免进程间随机化）。CLI `--host --port --name --quiet`。
- `heuristic.py`：`HeuristicPolicy(strategy)`，从 `start["rules"]` 读取数值；每回合：
  - 找自己与敌人；若 `hp <= 35` 且可治疗 → heal；
  - 若相邻敌人 → attack（collector 仅在 `hp < 50` 或 `strategy=aggressive` 时）；
  - 站在激活节点且 `strategy=collector` 或能量低于攻击成本 → gather；
  - 用 BFS 选择最近激活节点/敌人相邻空格；无路径时随机合法移动；
  - 本地校验能量/墙/占用/节点冷却；AI 不发送会被服务端拒绝的动作。
  - 三种 strategy 的差异必须体现在目标选择与治疗阈值；CLI `--strategy {aggressive,collector,balanced}`、`--seed`、`--quiet`。
- `llm_agent.py`：
  - `parse_action(text) -> dict | None`：从文本中提取第一个 `{...}` JSON；只接受 `move/dash/attack/gather/shield/heal/wait` 及合法方向；其它返回 None。
  - `LlmPolicy`：从 `NEON_ARENA_LLM_BASE_URL`（默认 `http://127.0.0.1:11434/v1`）、`NEON_ARENA_LLM_MODEL`、`NEON_ARENA_LLM_API_KEY`、`NEON_ARENA_LLM_TIMEOUT_MS` 读配置；用 `urllib.request` POST `/chat/completions`；prompt 包含规则、自己、敌人、节点、最近事件；解析失败/超时回退到启发式策略；`--no-fallback` 时返回 wait；API key 不打印。
  - 该文件只在运行时访问配置的 LLM，不引入第三方依赖。

- [ ] **Step 5: 实现终端观战与回放**

- `tools/spectator.py` 参数：`--host --port --replay --delay --plain --no-color --once`。
- 实时模式：连接后读 `welcome`，发送 `{"type":"spectate"}`；收到 `lobby` 打印大厅；`start` 记录 `start`；`state` 用 `render_board` 输出；`end` 打印排名；`--once` 结束退出，否则继续等待下一局。
- 回放模式：逐行读取 JSONL；`start/state/end` 分别渲染；`--delay` 秒；`--delay 0` 一次输出全部帧；不连接服务器。
- `--plain` 不清屏、无 ANSI；默认实时模式清屏（Windows 用 `os.system("cls")`，其它 `clear`），`--plain` 时绝不调用清屏。

- [ ] **Step 6: 跑 Agent 测试**

`cd agents; python -m unittest discover -s tests -v`
Expected: 全部 PASS。

- [ ] **Step 7: 手工连真实服务端**

```powershell
cd D:\NeonArena\server
python -m arena_server --host 127.0.0.1 --tick-ms 1000 --turn-limit 5 --no-logs
# 另开两个终端：
cd D:\NeonArena\agents
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha --strategy balanced
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Beta --strategy aggressive
# 第三个终端：
python -m tools.spectator --host 127.0.0.1 --port 7777 --once
```

Expected: 大厅 → 开局 → 5 回合内结束；观战器显示棋盘与排名；Bot 无异常退出。

- [ ] **Step 8: Commit**

```powershell
git add agents
git commit -m "feat(agents): add TCP SDK, bots and terminal spectator"
```

### Task 7: 独立人类 Web 客户端

**Files:**
- Create: `client/index.html`
- Create: `client/style.css`
- Create: `client/app.js`
- Create: `client/launcher.py`
- Create: `client/README.md`
- Create: `client/tests/test_static.py`

**Interfaces:**
- Produces:
  - 静态页面：连接页、大厅页、对局页、结算页
  - `launcher.py --host 127.0.0.1 --port 8090 --server http://127.0.0.1:8080 --no-open`
  - 浏览器端 `ApiClient` 语义：`health()`、`createSession(name)`、`recover(token)`、`state(token)`、`action(token, turn, action)`、`leave(token)`
  - token 存储键 `neon.token.<server>`；服务器地址键 `neon.server`

- [ ] **Step 1: 写静态约束测试**

```python
# client/tests/test_static.py
import re
import unittest
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]


class StaticTests(unittest.TestCase):
    def test_required_files(self):
        for name in ("index.html", "style.css", "app.js", "launcher.py"):
            self.assertTrue((CLIENT / name).is_file(), name)

    def test_no_external_runtime_dependencies(self):
        text = "\n".join((CLIENT / n).read_text(encoding="utf-8")
                         for n in ("index.html", "style.css", "app.js"))
        for bad in ("cdn.", "unpkg.com", "jsdelivr", "googleapis",
                    "<script src=\"http", "<link href=\"http"):
            self.assertNotIn(bad, text)

    def test_no_inner_html_with_user_data(self):
        app = (CLIENT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", app)
        self.assertIn("textContent", app)

    def test_server_address_is_configurable(self):
        app = (CLIENT / "app.js").read_text(encoding="utf-8")
        self.assertIn("neon.server", app)
        self.assertIn("/api/v1", app)
```

- [ ] **Step 2: 确认失败**

`cd client; python -m unittest discover -s tests -v`
Expected: FAIL（文件不存在）。

- [ ] **Step 3: 实现 HTML 结构**

- `index.html` 只引入本地 `style.css`、`app.js`；`lang="zh-CN"`；包含四个 `<section class="screen">`：
  - `#screen-connect`：服务器地址（默认 `http://127.0.0.1:8080`）、名字、连接按钮、健康检查状态、错误文本。
  - `#screen-lobby`：玩家列表（human/agent 标签）、人数、倒计时、规则速览、离开按钮。
  - `#screen-game`：Canvas `#board`、回合/倒计时/分数、`#hud-self`、`#hud-players`、`#event-log`、动作按钮（移动/冲刺/攻击/采集/护盾/治疗/等待）、方向 D-pad、状态提示。
  - `#screen-result`：胜者、排名表、统计、“再来一局”、“离开”。
- 所有用户可见名称通过 JS `textContent` 写入；HTML 中不硬编码玩家名。
- 提供 `aria-live="polite"` 的状态区与按钮 `aria-label`；按钮使用 `<button type="button">`。

- [ ] **Step 4: 实现霓虹样式**

- 背景 `#070b14`；青色/品红/亮绿/琥珀玩家色；网格低亮；墙深色块+霓虹边；节点菱形发光，冷却时显示数字。
- 桌面：棋盘左、HUD 右、操作区底部；窄屏（`max-width: 860px`）：棋盘在上、HUD 与操作在下；Canvas 容器 `aspect-ratio: 1`。
- 支持 `prefers-reduced-motion: reduce`：关闭脉冲、扫描线、过渡。
- 倒计时进度条用 CSS 变量 `--progress`；提交后显示“等待其他玩家”。
- 不引入外部字体/图片；图标用 CSS 形状或 Unicode 字符。

- [ ] **Step 5: 实现 app.js**

- 状态：`server, token, view, pollTimer, pollInFlight, backoff, selectedAction, clockOffset`。
- `api(path, {method, body, auth})`：`fetch(server + "/api/v1" + path)`；`Authorization: Bearer token`；解析 JSON；抛 `ApiError(status, code, message)`；不把 token 写入 URL。
- 启动：读 `localStorage["neon.server"]` 与该服务器的 token；有 token 先 `GET /state` 恢复；401 清除 token 回连接页。
- 连接：`GET /health` 校验 `protocol`；`POST /sessions {name}`；保存 token；进入大厅；启动轮询。
- 轮询：单次 `setTimeout` 链，避免重复定时器；大厅 800ms、比赛 350ms、结束 1500ms；页面隐藏 1500ms；网络错误指数退避最大 5s，显示“重连中”。
- 提交：`POST /actions {turn, action}`；成功后本地 `submitted=true`；400 显示错误并解锁；409 立即刷新；每回合只允许一个待提交动作。
- 操作：
  - 点击“移动/冲刺/攻击”进入方向模式；按 WASD/方向键或 D-pad 提交带方向动作；`Esc` 取消。
  - 采集/护盾/治疗/等待直接提交；数字键 `1..7` 选择；`Space` 等待。
  - 能量不足/HP 满/护盾满/非节点时按钮置灰，但服务端仍是最终裁判。
- 渲染：
  - `drawBoard(match)`：DPR 缩放；格子、墙、节点、玩家圆形+首字母、HP 条、护盾环、能量弧、自己脉冲圈；坐标来自 `arena.walls/nodes` 与 `players[].pos`。
  - `renderHud`：自己 HP/能量/护盾/分数；按分数排序的玩家条；最近 8 条事件用 `formatEvent` 转中文。
  - 倒计时：`remaining = match.reply_by_ms - (Date.now() + clockOffset)`，`clockOffset = view.server.now_ms - Date.now()`；每 100ms 更新；到 0 显示“结算中”。
- 结算：展示 `result.winner`、`standings`、伤害/击杀/采集；“再来一局”带 token `POST /sessions` 重新排队；“离开”`DELETE /sessions` 并清 token。
- 断线：网络错误保留 token；收到 401 才清 token；服务器重启提示“会话已失效，请重新加入”。
- 安全：所有动态文本用 `textContent`；不拼接 `innerHTML`；不执行服务器返回的 HTML。

- [ ] **Step 6: 实现 launcher.py**

- 只用标准库 `http.server`/`socketserver`/`argparse`/`webbrowser`。
- 默认绑定 `127.0.0.1:8090`；只服务 `client/` 目录；只允许 GET/HEAD；路径解析后必须仍在目录内；禁止列目录。
- `--server` 生成 `http://127.0.0.1:8090/?server=<urlencoded>`；`--no-open` 不打开浏览器；启动失败（端口占用）打印明确错误。
- 不代理 `/api`、不读取服务端目录、不修改任何游戏状态。

- [ ] **Step 7: 跑静态测试并手工验收**

`cd client; python -m unittest discover -s tests -v`
Expected: 4 tests PASS。

```powershell
cd D:\NeonArena\server
python -m arena_server --host 127.0.0.1 --tick-ms 15000 --turn-limit 5 --no-logs
cd D:\NeonArena\agents
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha
cd D:\NeonArena\client
python launcher.py --server http://127.0.0.1:8080
```

浏览器验收：
1. 连接页显示健康检查成功；输入名字进入大厅。
2. 与 Bot 开局，倒计时、棋盘、HUD、事件流正常。
3. 键盘与鼠标各提交一次动作并看到结算。
4. 刷新页面后恢复当前对局。
5. 结算页显示排名；“再来一局”能重新排队。
6. 控制台无报错，Network 中无外部域名请求。

- [ ] **Step 8: Commit**

```powershell
git add client
git commit -m "feat(client): add standalone neon web client and launcher"
```

---

### Task 8: 跨进程端到端测试与一键脚本

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_e2e.py`
- Create: `scripts/start_server.ps1`
- Create: `scripts/demo.ps1`
- Create: `scripts/play.ps1`

**Interfaces:**
- Produces: 根目录 `python -m unittest discover -s tests -v` 可跑的跨进程验收；三个 PowerShell 编排脚本，只做进程启动/清理，不含游戏逻辑。

- [ ] **Step 1: 写失败 E2E 测试**

```python
# tests/test_e2e.py
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
AGENTS_DIR = ROOT / "agents"


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def http_json(base, method, path, body=None, token=None, timeout=3):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.procs = []
        self.server = None
        self.tcp_port = free_port()
        self.api_port = free_port()
        self.base = f"http://127.0.0.1:{self.api_port}/api/v1"

    def tearDown(self):
        for proc in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def start(self, args, cwd, quiet=True):
        kwargs = {
            "cwd": str(cwd),
            "stdout": subprocess.DEVNULL if quiet else subprocess.PIPE,
            "stderr": subprocess.STDOUT if quiet else subprocess.PIPE,
            "text": True,
        }
        proc = subprocess.Popen([sys.executable, *args], **kwargs)
        self.procs.append(proc)
        return proc

    def wait_health(self, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.server.poll() is not None:
                output = self.server.stdout.read() if self.server.stdout else ""
                self.fail(f"server exited early:\n{output}")
            try:
                status, data = http_json(self.base, "GET", "/health")
                if status == 200 and data.get("ok"):
                    return
            except Exception:
                pass
            time.sleep(0.1)
        self.fail("server health check timed out")

    def test_human_and_agents_finish_real_match(self):
        self.server = self.start([
            "-m", "arena_server",
            "--host", "127.0.0.1",
            "--tcp-port", str(self.tcp_port),
            "--api-port", str(self.api_port),
            "--tick-ms", "300",
            "--min-turn-ms", "0",
            "--turn-limit", "3",
            "--min-players", "3",
            "--lobby-wait-ms", "100",
            "--no-logs",
        ], SERVER_DIR, quiet=False)
        self.wait_health()

        status, data = http_json(self.base, "POST", "/sessions",
                                 body={"name": "Human"})
        self.assertEqual(status, 200, data)
        token = data["token"]

        # 人类先排队，确保不会在两个 Bot 之间提前开赛
        for name in ("BotA", "BotB"):
            self.start([
                "-m", "bots.random_bot",
                "--host", "127.0.0.1",
                "--port", str(self.tcp_port),
                "--name", name,
                "--quiet",
            ], AGENTS_DIR)

        view = None
        deadline = time.time() + 30
        while time.time() < deadline:
            status, data = http_json(self.base, "GET", "/state", token=token)
            self.assertEqual(status, 200, data)
            view = data["view"]
            if view["mode"] == "match":
                match = view["match"]
                self.assertEqual({p["kind"] for p in match["players"]},
                                 {"agent", "human"})
                if not match["submitted"]:
                    status, action_data = http_json(
                        self.base, "POST", "/actions", token=token,
                        body={"turn": match["turn"],
                              "action": {"type": "wait"}},
                    )
                    self.assertIn(status, (200, 409), action_data)
            elif view["mode"] == "ended":
                break
            time.sleep(0.05)

        self.assertIsNotNone(view)
        self.assertEqual(view["mode"], "ended")
        result = view["result"]
        self.assertIn(result["reason"],
                      {"last_standing", "turn_limit", "mutual_destruction"})
        self.assertEqual(len(result["standings"]), 3)
        self.assertEqual({p["name"] for p in result["standings"]},
                         {"Human", "BotA", "BotB"})

        status, data = http_json(self.base, "GET", "/")
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])
        root = f"http://127.0.0.1:{self.api_port}"
        for path in ("/", "/index.html", "/client/app.js", "/client/style.css"):
            status, data = http_json(root, "GET", path)
            self.assertEqual(status, 404, path)
            self.assertFalse(data["ok"], path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 确认失败**

`python -m unittest tests.test_e2e -v`
Expected: FAIL（服务端/客户端/脚本尚未完成或端口不可用）。

- [ ] **Step 3: 实现三个 PowerShell 脚本**

- `scripts/start_server.ps1`：参数 `-BindHost 0.0.0.0 -TcpPort 7777 -ApiPort 8080 -TickMs 15000 -TurnLimit 80 -NoLogs -Verbose`；`Push-Location server` 后 `& python -m arena_server ...`；`finally` 恢复目录。不要在脚本里写死项目盘符，用 `$PSScriptRoot` 推导根目录。
- `scripts/demo.ps1`：启动服务端（`BindHost=127.0.0.1`、短 tick 便于观察）、3 个启发式 Bot（aggressive/collector/balanced）；可选 `-NoSpectator`、`-OpenClient`；打印“按 Enter 停止”；`finally` 中先停 Bot 再停服务端。观战器用新 PowerShell 窗口运行 `python -m tools.spectator`。
- `scripts/play.ps1`：启动服务端 + 2 个启发式 Bot + `client/launcher.py`；默认打开浏览器；打印“按 Enter 停止”；`finally` 清理所有子进程。
- 三个脚本都必须支持端口参数；不得包含游戏规则、不得直接修改日志或源码。
- PowerShell 5.1 兼容：不使用 `??`、`?.`、`ForEach-Object -Parallel`；路径全部加引号。

- [ ] **Step 4: 跑 E2E**

`python -m unittest tests.test_e2e -v`
Expected: PASS，输出包含 Human/BotA/BotB 的最终排名；无残留 python 进程。

- [ ] **Step 5: Commit**

```powershell
git add tests scripts
git commit -m "test: add cross-process end-to-end match and demo scripts"
```

---

### Task 9: 文档、OpenAPI 与最终验收

**Files:**
- Create: `README.md`
- Create: `server/README.md`
- Create: `agents/README.md`
- Create: `docs/RULES.md`
- Create: `docs/PROTOCOL.md`
- Create: `docs/HTTP_API.md`
- Create: `docs/openapi.yaml`

**Interfaces:**
- Produces: 与实现一致的运行说明、规则、TCP/HTTP 契约与 OpenAPI 3.0 描述；所有命令可在 Windows PowerShell 直接执行。

- [ ] **Step 1: 写总 README**

`README.md` 必须包含：

1. 一句话介绍与真实界面截图（实现完成后补充；若暂未截图，不写占位图或假图说明）。
2. 架构图：`server/`（TCP 7777 + HTTP 8080）、`agents/`、`client/` 三个独立产物；明确“服务端不托管客户端”。
3. 快速开始：
   - 服务端：`cd server; python -m arena_server --host 0.0.0.0`
   - 人类：`cd client; python launcher.py --server http://127.0.0.1:8080`
   - Agent：`cd agents; python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha`
4. 远程部署：防火墙放行 7777/8080、客户端本地 8090 不暴露、NAT 说明、无 TLS 风险。
5. 测试命令、脚本说明、目录结构、文档链接、零依赖说明。
6. 明确“结束一局后需重新 join/排队”，避免误以为自动连赛。

- [ ] **Step 2: 写规则与协议文档**

- `docs/RULES.md`：地图、出生点、节点、属性、行动表、结算顺序、伤害/击杀/计分、胜负排名、节点冷却、超时判负；数值必须与 `config.py` 完全一致。
- `docs/PROTOCOL.md`：TCP NDJSON 约定、`welcome/join/joined/lobby/spectate/spectating/action/action_ack/start/state/end/leave/left/ping/pong/error` 全部消息、字段表、错误码、限流、断线语义、完整一局示例。
- `docs/HTTP_API.md`：基础地址、Bearer token、CORS、每个端点的请求/响应、状态视图、错误码、PowerShell `Invoke-RestMethod` 与 curl 示例、轮询建议、混合对局流程。
- 三份文档中的端口、数值、错误码必须从实现/规格核对，不能复制过时草稿。

- [ ] **Step 3: 写 OpenAPI**

`docs/openapi.yaml` 使用 OpenAPI 3.0.3，至少包含：

- `servers: [{url: "http://127.0.0.1:8080/api/v1"}]`
- 路径：`/health`、`/rules`、`/sessions`（POST/DELETE）、`/state`（GET）、`/actions`（POST）
- 组件：`Health`、`RulesResponse`、`SessionRequest`、`SessionResponse`、`StateResponse`、`LobbyView`、`MatchView`、`EndedView`、`PlayerView`、`Action`、`ActionRequest`、`ActionResponse`、`Error`
- `securitySchemes.BearerAuth`（http bearer）与受保护端点的 `security`
- 所有响应都描述 `ok` 外层结构与错误对象
- 不把 token 写成示例真实值；用 `<token>`

- [ ] **Step 4: 校验文档与 OpenAPI**

```powershell
python -c "import yaml, pathlib; p=pathlib.Path('docs/openapi.yaml'); d=yaml.safe_load(p.read_text(encoding='utf-8')); assert d['openapi'].startswith('3.'); paths=set(d['paths']); need={'/health','/rules','/sessions','/state','/actions'}; assert need <= paths, need-paths; print('openapi ok')"
```

Expected: `openapi ok`。PyYAML 仅用于本机校验，不是运行依赖。

```powershell
git grep -n "TODO\|TBD\|FIXME\|PLAN_PART" -- . ":(exclude)docs/superpowers/plans/*"
```

Expected: 无输出（计划文件本身允许包含流程文字，但不得有未完成占位实现）。

- [ ] **Step 5: 全量测试**

```powershell
cd D:\NeonArena\server
python -m unittest discover -s tests -v
cd D:\NeonArena\agents
python -m unittest discover -s tests -v
cd D:\NeonArena
python -m unittest discover -s tests -v
```

Expected: 三组全部 PASS；E2E 输出 3 人排名。

- [ ] **Step 6: 浏览器与真人验收**

1. 启动真实服务端（不加 `--no-logs`），确认 `server/logs/` 生成 JSONL。
2. 启动两个 Bot 与 `client/launcher.py`，用浏览器完成至少 3 个回合。
3. 刷新页面，确认 token 恢复对局。
4. 关闭一个 Bot 进程，确认其立即判负、剩余玩家继续。
5. 完成一局，确认结算页、排名、日志文件；用 `python -m tools.spectator --replay <日志>` 回放。
6. 检查浏览器控制台无报错；Network 只有本地客户端静态资源与 `127.0.0.1:8080/api/v1`。
7. 确认服务端根路径与 `/client/*` 均返回 404 JSON，不返回任何 HTML。

- [ ] **Step 7: 最终提交**

```powershell
cd D:\NeonArena
git status --short
git add README.md server/README.md agents/README.md docs
git commit -m "docs: add runbooks, protocol reference and OpenAPI"
git log --oneline -10
```

Expected: 工作树干净；提交历史按 Task 递增；设计文档与实现一致。

---

## 验收清单（Definition of Done）

- [ ] `server/`、`agents/`、`client/` 三个目录可独立复制/部署，互不导入运行时代码。
- [ ] 服务端 HTTP 只返回 JSON；根路径、`/client/*`、未知路径均为 404 JSON，不返回 HTML/CSS/JS。
- [ ] Agent 可通过 `IP:7777` 加入，人类可通过 `IP:8080` 加入，二者同场完成一局。
- [ ] 服务端规则、计分、结算、判负、排名与 `docs/RULES.md` 一致。
- [ ] 三个示例 Agent 可运行；LLM Agent 有超时/解析失败回退。
- [ ] 终端观战与 JSONL 回放可用。
- [ ] 浏览器客户端支持连接任意服务器、键盘/鼠标操作、刷新恢复、断线重连、结算与再来一局。
- [ ] `server`、`agents`、根 E2E 测试全部通过。
- [ ] README、协议、HTTP API、OpenAPI、部署与防火墙说明齐全。
- [ ] `scripts/start_server.ps1`、`demo.ps1`、`play.ps1` 可复现人类 + 多 Agent 对局。
- [ ] 零第三方运行依赖；Windows PowerShell 5.1 与 Python 3.10 可执行所有文档命令。

