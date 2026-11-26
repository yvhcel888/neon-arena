# NEON ARENA

**Language / 语言:** [English](#english-overview) | [中文](#chinese-overview)

This README presents the complete documentation in English, followed by a complete Chinese translation. Commands, versions, defaults, and numeric rules are intentionally identical in both sections.

---

<a id="english-overview"></a>

## English

### Contents

- [Overview](#english-overview)
- [Architecture and deployment boundaries](#architecture-and-deployment-boundaries)
- [Requirements and dependencies](#requirements-and-dependencies)
- [Quick start](#quick-start)
- [Five modes and rotation](#five-modes-and-rotation)
- [Strict turn-based timing](#strict-turn-based-timing)
- [Web client visuals and controls](#web-client-visuals-and-controls)
- [Observe and replay](#observe-and-replay)
- [Remote deployment and security](#remote-deployment-and-security)
- [Tests and scripts](#tests-and-scripts)
- [Directory structure](#directory-structure)
- [Documentation](#documentation)

### Overview

NEON ARENA is a zero-dependency, server-authoritative tactical arena where 2–4 human and Agent players share strict turn-based decision windows across five game modes.

The shipped server is version `1.0.0`; the TCP protocol and HTTP API versions are `1` and `/api/v1`, respectively.

**At a glance**

- Five modes: Classic, King of the Hill, Team 2v2, Survival, and Bounty.
- Strict, shared turn deadlines with simultaneous resolution—no real-time movement or private extensions.
- Independent server, Agent, and Web client products.
- Standard-library Python runtime with no package installation or build step.

### Architecture and deployment boundaries

```text
 Human player's PC                         Server host
 ------------------                        -------------------------------
 client/launcher.py                         server/arena_server/
   http://127.0.0.1:8090                      TCP  :7777  NDJSON
   browser -> static HTML/CSS/JS  --HTTP-->   HTTP :8080  JSON /api/v1
   token stays in browser localStorage        lobby + one active match
                                             authoritative engine + JSONL

 Agent host(s)
 -------------------------------
 agents/arena_agent + agents/bots
   Python SDK / random / heuristic / LLM
   ------------------- TCP NDJSON --> server IP:7777
```

`server/`, `agents/`, and `client/` are independent deployable products. They do not import one another's runtime code. **The game server does not host the Web client**: port `8080` returns JSON only, while the client is served locally on port `8090` or from a static site.

There is one active match per server. Additional players wait in the same lobby. After a match, participants are idle and **must join/queue again**; the reference bots exit after one match, and the Web client requires “Play again” or a new connection.

### Requirements and dependencies

- Python 3.10+ for `server/`, `agents/`, and the optional client launcher.
- A modern browser for the Web client.
- Windows PowerShell 5.1, PowerShell 7, macOS, or Linux.
- No package installation, build step, CDN, framework, external font, or third-party runtime library.
- Node.js 18+ only for the client's JavaScript tests; it is not required by the client runtime.

PyYAML is optional and used only for local OpenAPI validation; it is not an application dependency.

### Quick start

Use three terminals. The commands below use Windows PowerShell paths and also work in Git Bash when the path separator is adjusted. Replace `D:\NeonArena` if the repository is located elsewhere.

#### 1. Start the authoritative server

```powershell
Set-Location D:\NeonArena\server
python -m arena_server --host 0.0.0.0
```

This starts Agent TCP on `7777`, HTTP JSON on `8080`, and automatic mode rotation. JSONL match logs are written under `server/logs/` by default.

#### 2. Start the independent Web client

```powershell
Set-Location D:\NeonArena\client
python launcher.py --server http://127.0.0.1:8080
```

Open `http://127.0.0.1:8090/`, enter a name, and connect. The launcher listens only on loopback by default. `--server` is stored in the opened URL as a query parameter; the session token is never placed in the URL.

#### 3. Add Agents

```powershell
Set-Location D:\NeonArena\agents
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha
```

In another terminal:

```powershell
Set-Location D:\NeonArena\agents
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Beta --strategy aggressive
```

A random baseline and an optional LLM Agent are also available:

```powershell
python -m bots.random_bot --host 127.0.0.1 --port 7777 --name Random --quiet
python -m bots.llm_agent --host 127.0.0.1 --port 7777 --name LLM
```

Run these bot commands from `agents/`. The lobby starts after the selected mode's minimum is reached and the default 5-second countdown expires. Reaching `--max-players` (default `4`) starts immediately. TCP Agents and HTTP humans share the same queue and match.

### Five modes and rotation

| Mode ID | Display name | Minimum at start | Mode-specific numbers | End reasons |
| --- | --- | ---: | --- | --- |
| `classic` | Classic | 2 | Kill +25; gather +10; actual HP damage +1/point | Base reasons |
| `king` | King of the Hill | 2 | Center `[6,6]..[8,8]`; 5 base points/turn plus streak bonus capped at 5; total hill award capped at 10 points/turn; target 100 | Base reasons plus `score_limit` |
| `team` | Team 2v2 | 4 (exactly) | `P1/P2` vs `P3/P4`; friendly fire blocked; team score is member score sum | Base reasons; team result uses `winner.kind="team"` and `team_standings` |
| `survival` | Survival | 2 | Shrink after turns 6/12/18/24/30; storm deals 12 true HP damage after each shrink | Base reasons |
| `bounty` | Bounty | 2 | Assigned-target damage score x2; target kill rewards 50/55/60/65; target 150 | Base reasons plus `score_limit` |

**Base reasons:** `last_standing`, `mutual_destruction`, `turn_limit`, and `aborted`.

Every mode also retains the configured turn limit (default `80`). Detailed numbers and resolution order are in [docs/RULES.md](docs/RULES.md).

#### Rotation and fixed modes

The default rotation is:

```text
classic -> king -> team -> survival -> bounty -> classic
```

The server scans from the rotation cursor and chooses the first mode whose minimum is met. With 2–3 waiting players it skips `team` and advances the cursor, so team mode is not immediately retried. With 4 players it can select team mode. A fixed mode never advances the rotation cursor.

```powershell
# Explicit rotation (also the default)
python -m arena_server --host 0.0.0.0 --mode rotation

# Always play King of the Hill
python -m arena_server --host 0.0.0.0 --mode king

# Always wait for exactly four players and play Team 2v2
python -m arena_server --host 0.0.0.0 --mode team --max-players 4
```

### Strict turn-based timing

All five modes are turn-based, not real-time:

1. The server broadcasts `state` with `turn` and absolute Unix-millisecond deadline `reply_by_ms`.
2. Every living player has the same window (`--tick-ms`, default `15000`). A legal resubmission replaces that player's earlier pending action while the window is open.
3. The turn resolves when all living players have submitted, but never before `--min-turn-ms` (default `250`); otherwise it resolves at the deadline.
4. The server applies movement, combat, resources, mode effects, and victory checks atomically.

The server rejects submissions after the deadline with `turn_closed`. An action produced late by an Agent is recorded only in that client's `expired_actions`; it is not submitted and cannot affect the resolved turn retroactively. A player with four consecutive missed or invalid submissions is forfeited.

#### LLM timing: 30/60-second windows

For LLM Agents, start the server with a larger shared window:

```powershell
# Server terminal: 30-second shared window
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 30000
# Server terminal: slower models/endpoints, 60-second shared window
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 60000

# LLM Agent terminal: raise the request cap to match the chosen server window
$env:NEON_ARENA_LLM_TIMEOUT_MS = "24000"  # use with --tick-ms 30000
$env:NEON_ARENA_LLM_TIMEOUT_MS = "48000"  # use instead with --tick-ms 60000
```

The LLM bot caps its request budget at the smallest of `NEON_ARENA_LLM_TIMEOUT_MS`, 80% of `tick_ms`, and 90% of the remaining time before `reply_by_ms`. Parsing failures, HTTP errors, and timeouts fall back to the mode-aware heuristic policy; `--no-fallback` waits instead. No player receives a private extension.

### Web client visuals and controls

The same action panel and controls are used in every mode; no mode adds buttons or changes input rules.

| Mode | Visualization |
| --- | --- |
| `classic` | Standard neon board, HP/energy/shield, scores, and node cooldowns |
| `king` | Center-zone overlay, target score, and `hill_streak` HUD |
| `team` | Team-colored rings/borders, team HUD, team result table, and winning members |
| `survival` | Storm mask outside `mode_state.zone`, safe-zone boundary, next shrink, and `in_storm` alert |
| `bounty` | Dashed line and target marker for `bounty_target`, plus `bounty_streak` |

Controls: click/tap an action and direction, use WASD or arrow keys for movement, press `1..7` for move/dash/attack/gather/shield/heal/wait, press `Space` to wait, and press `Esc` to cancel direction selection. Refresh restores the current lobby, match, or ended view using the server-scoped token. See [client/README.md](client/README.md).

### Observe and replay

From `agents/`:

```powershell
python -m tools.spectator --host 127.0.0.1 --port 7777 --once
python -m tools.spectator --host 127.0.0.1 --port 7777 --plain
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0.2 --plain
```

Each match log contains `start`, one `state` per completed turn, and `end`; an immediate out-of-turn forfeit may add a `state` record whose `turn` and `events_turn` are the current open turn. All records include `mode` and `mode_state`; mode events such as `hill_score`, `storm_shrink`, `storm_damage`, `bounty_complete`, `bounty_retarget`, and `friendly_blocked` are rendered by the terminal spectator.

### Remote deployment and security

- On a trusted LAN/VPN, allow inbound **TCP 7777** for Agents/spectators and **TCP 8080** for the HTTP API. Do not expose raw TCP `7777` directly to an untrusted network.
- Keep the client launcher's **TCP 8090** on the player's machine; do not expose it as a game-service port.
- Clients and Agents initiate outbound connections, so they need no inbound NAT mapping. The server needs a reachable LAN address, public IP, or VPN/tunnel endpoint.
- A Windows firewall rule can be created by an administrator:

  ```powershell
  New-NetFirewallRule -DisplayName "NEON ARENA" -Direction Inbound -Protocol TCP -LocalPort 7777,8080 -Action Allow
  ```

- The server has **no TLS**. On an untrusted network, game traffic, names, and bearer tokens can be observed or modified. Use a trusted LAN or VPN. An HTTP TLS reverse proxy protects only port `8080`; it does **not** protect plaintext TCP `7777`. Remote TCP Agents/spectators require a VPN, SSH tunnel/local forwarding, or a TLS wrapper that can carry raw TCP. An HTTPS client page cannot call a plain HTTP API because of browser mixed-content rules.
- CORS defaults to `*`. Restrict it to the actual client origin in production. From `server/`:

  ```powershell
  python -m arena_server --host 0.0.0.0 --cors-origin "http://arena.example.com"
  ```

- The HTTP token is a session credential, not an account. Do not share it. Anyone who can reach the open ports can create a session or Agent connection unless network policy restricts them.
- Server root, `/client/*`, and unknown paths return JSON `404`; the server never serves HTML/CSS/JS.

### Tests and scripts

Run each shipped suite from its own directory:

```powershell
Set-Location D:\NeonArena\server
python -m unittest discover -s tests -p "test_*.py" -v

Set-Location D:\NeonArena\agents
python -m unittest discover -s tests -v

Set-Location D:\NeonArena\client
python -m unittest discover -s tests -v
node --test

Set-Location D:\NeonArena
python -m unittest discover -s tests -v
```

The root suite contains cross-process human + Agent matches for classic, king, and team modes, JSON-only HTTP checks, and PowerShell 5.1 orchestration contract tests.

#### PowerShell scripts

From the repository root:

```powershell
# Start only the server; forwards ports, timing, player limits, and mode
.\scripts\start_server.ps1 -Mode king

# Server + three requeueing heuristic bots + terminal spectator
.\scripts\demo.ps1 -Mode rotation
.\scripts\demo.ps1 -Mode king -NoSpectator -OpenClient

# Server + two requeueing heuristic bots + Web client launcher
.\scripts\play.ps1 -Mode rotation
.\scripts\play.ps1 -Mode king -NoOpen
```

`start_server.ps1` defaults to `0.0.0.0`, ports 7777/8080, 15000 ms turns, and rotation. `demo.ps1` defaults to loopback, a faster 1500 ms turn, three bots, and a spectator. `play.ps1` defaults to loopback, two bots, a human-oriented minimum of 3, and the client on 8090. `demo.ps1` and `play.ps1` wait for Enter and clean up their child process trees in `finally` blocks.

#### OpenAPI validation

Validate the OpenAPI text and, when PyYAML is available, parse it:

```powershell
python -c "import pathlib; p=pathlib.Path('docs/openapi.yaml'); text=p.read_text(encoding='utf-8'); assert '/health' in text and '/actions' in text and 'score_limit' in text and 'mode_state' in text; print('openapi text ok')"
python -c "import yaml, pathlib; d=yaml.safe_load(pathlib.Path('docs/openapi.yaml').read_text(encoding='utf-8')); assert d['openapi'].startswith('3.'); need={'/health','/rules','/sessions','/state','/actions'}; assert need <= set(d['paths']); print('openapi ok')"
```

### Directory structure

```text
D:\NeonArena\
├─ README.md
├─ server\
│  ├─ arena_server\          # authoritative engine, TCP, HTTP, lobby, modes, logs
│  ├─ tests\
│  ├─ README.md
│  └─ logs\                  # generated at runtime
├─ agents\
│  ├─ arena_agent\           # standalone Python SDK and helpers
│  ├─ bots\                  # random, heuristic, LLM
│  ├─ tools\spectator.py     # live terminal viewer and JSONL replay
│  ├─ tests\
│  └─ README.md
├─ client\
│  ├─ index.html
│  ├─ style.css
│  ├─ app.js
│  ├─ launcher.py
│  ├─ tests\
│  └─ README.md
├─ docs\
│  ├─ RULES.md
│  ├─ PROTOCOL.md
│  ├─ HTTP_API.md
│  ├─ openapi.yaml
│  └─ superpowers\           # design/spec/plan history
├─ tests\
│  ├─ test_e2e.py            # real server + TCP Agents + HTTP human
│  └─ test_scripts.py        # PowerShell 5.1 script contracts
└─ scripts\
   ├─ start_server.ps1
   ├─ demo.ps1
   └─ play.ps1
```

### Documentation

- [Server operations](server/README.md)
- [Agent SDK and bots](agents/README.md)
- [Web client guide](client/README.md)
- [Game rules and mode numbers](docs/RULES.md)
- [TCP NDJSON protocol](docs/PROTOCOL.md)
- [HTTP API and client flow](docs/HTTP_API.md)
- [OpenAPI 3.0.3 contract](docs/openapi.yaml)

---

<a id="chinese-overview"></a>

## 中文

### 目录

- [项目概览](#chinese-overview)
- [架构与部署边界](#架构与部署边界)
- [环境要求与依赖](#环境要求与依赖)
- [快速开始](#快速开始)
- [五种模式与轮换](#五种模式与轮换)
- [严格回合制计时](#严格回合制计时)
- [Web 客户端视觉与操作](#web-客户端视觉与操作)
- [观战与回放](#观战与回放)
- [远程部署与安全](#远程部署与安全)
- [测试与脚本](#测试与脚本)
- [目录结构](#目录结构)
- [组件文档](#组件文档)

### 项目概览

NEON ARENA 是一个零依赖、服务端权威的战术竞技场，支持 2–4 名人类玩家与 Agent 玩家混合对战，并在五种游戏模式中共享严格的回合制决策窗口。

当前发布的服务端版本为 `1.0.0`；TCP 协议版本为 `1`，HTTP API 版本路径为 `/api/v1`。

**核心特性**

- 五种模式：经典战、占山为王、团队 2v2、生存收缩和悬赏追击。
- 所有玩家共享严格的回合截止时间，动作同时结算；没有实时移动，也没有私人延时。
- 服务端、Agent 和 Web 客户端是彼此独立的产品。
- Python 运行时仅使用标准库，无需安装依赖包或执行构建步骤。

### 架构与部署边界

```text
 人类玩家电脑                            服务端主机
 ------------------                        -------------------------------
 client/launcher.py                         server/arena_server/
   http://127.0.0.1:8090                      TCP  :7777  NDJSON
   browser -> static HTML/CSS/JS  --HTTP-->   HTTP :8080  JSON /api/v1
   token stays in browser localStorage        lobby + one active match
                                             authoritative engine + JSONL

 Agent 主机
 -------------------------------
 agents/arena_agent + agents/bots
   Python SDK / random / heuristic / LLM
   ------------------- TCP NDJSON --> server IP:7777
```

`server/`、`agents/` 和 `client/` 是三个可独立部署的产品，彼此不会导入对方的运行时代码。**游戏服务端不托管 Web 客户端**：`8080` 端口仅返回 JSON，客户端由本机 `8090` 端口或静态站点提供。

每台服务端同一时间只运行一场比赛，额外玩家留在同一个大厅等待。比赛结束后，参与者会进入空闲状态，**必须重新加入或排队**；参考机器人在一场比赛后退出，Web 客户端需要点击“再来一局”或重新建立连接。

### 环境要求与依赖

- `server/`、`agents/` 和可选的客户端启动器需要 Python 3.10+。
- Web 客户端需要现代浏览器。
- 支持 Windows PowerShell 5.1、PowerShell 7、macOS 和 Linux。
- 无需安装依赖包，无需构建步骤，不使用 CDN、框架、外部字体或第三方运行时库。
- Node.js 18+ 仅用于客户端 JavaScript 测试，客户端运行本身不需要 Node.js。

PyYAML 为可选项，仅用于本地 OpenAPI 校验，不是应用运行依赖。

### 快速开始

请打开三个终端。以下命令使用 Windows PowerShell 路径；在 Git Bash 中调整路径分隔符后也可运行。如果仓库位于其他目录，请替换 `D:\NeonArena`。

#### 1. 启动权威服务端

```powershell
Set-Location D:\NeonArena\server
python -m arena_server --host 0.0.0.0
```

服务端将在 `7777` 端口启动 Agent TCP，在 `8080` 端口启动 HTTP JSON API，并自动轮换模式。JSONL 比赛日志默认写入 `server/logs/`。

#### 2. 启动独立 Web 客户端

```powershell
Set-Location D:\NeonArena\client
python launcher.py --server http://127.0.0.1:8080
```

打开 `http://127.0.0.1:8090/`，输入名称并连接。启动器默认仅监听回环地址。`--server` 会作为查询参数保存在打开的 URL 中；会话令牌永远不会放入 URL。

#### 3. 添加 Agent

```powershell
Set-Location D:\NeonArena\agents
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Alpha
```

在另一个终端中：

```powershell
Set-Location D:\NeonArena\agents
python -m bots.heuristic --host 127.0.0.1 --port 7777 --name Beta --strategy aggressive
```

另提供随机基线机器人和可选的 LLM Agent：

```powershell
python -m bots.random_bot --host 127.0.0.1 --port 7777 --name Random --quiet
python -m bots.llm_agent --host 127.0.0.1 --port 7777 --name LLM
```

请在 `agents/` 目录中运行这些机器人命令。所选模式达到最低人数后，会启动默认 5 秒倒计时；达到 `--max-players`（默认 `4`）时立即开始。TCP Agent 与 HTTP 人类玩家共用同一个队列和比赛。

### 五种模式与轮换

| 模式 ID | 显示名称 | 开局最低人数 | 模式专属数值 | 结束原因 |
| --- | --- | ---: | --- | --- |
| `classic` | 经典战 | 2 | 击杀 +25；采集 +10；实际 HP 伤害每点 +1 | 基础原因 |
| `king` | 占山为王 | 2 | 中心区 `[6,6]..[8,8]`；每回合基础 5 分，连胜奖励上限 5 分；占山总得分上限为每回合 10 分；目标 100 分 | 基础原因加 `score_limit` |
| `team` | 团队 2v2 | 4（必须恰好 4 人） | `P1/P2` 对阵 `P3/P4`；阻止友方伤害；队伍得分为成员得分之和 | 基础原因；队伍结果使用 `winner.kind="team"` 和 `team_standings` |
| `survival` | 生存收缩 | 2 | 第 6/12/18/24/30 回合后收缩；每次收缩后风暴造成 12 点真实 HP 伤害 | 基础原因 |
| `bounty` | 悬赏追击 | 2 | 对指定目标的伤害得分翻倍；击杀目标奖励 50/55/60/65；目标 150 分 | 基础原因加 `score_limit` |

**基础原因：** `last_standing`、`mutual_destruction`、`turn_limit` 和 `aborted`。

所有模式都保留配置的回合上限（默认 `80`）。详细数值和结算顺序见 [docs/RULES.md](docs/RULES.md)。

#### 轮换与固定模式

默认轮换顺序为：

```text
classic -> king -> team -> survival -> bounty -> classic
```

服务端从轮换游标位置向后扫描，选择第一个满足最低人数的模式。等待玩家为 2–3 人时会跳过 `team` 并推进游标，因此不会立即重试团队模式；有 4 名玩家时可以选择团队模式。固定模式不会推进轮换游标。

```powershell
# 显式轮换（也是默认值）
python -m arena_server --host 0.0.0.0 --mode rotation

# 始终进行占山为王
python -m arena_server --host 0.0.0.0 --mode king

# 始终等待恰好四名玩家并进行团队 2v2
python -m arena_server --host 0.0.0.0 --mode team --max-players 4
```

### 严格回合制计时

五种模式都是回合制，而非实时制：

1. 服务端广播包含 `turn` 和绝对 Unix 毫秒截止时间 `reply_by_ms` 的 `state`。
2. 每名存活玩家共享同一个窗口（`--tick-ms`，默认 `15000`）。窗口开放期间，合法的重新提交会替换该玩家先前待处理的动作。
3. 所有存活玩家都提交后回合才会结算，但不会早于 `--min-turn-ms`（默认 `250`）；否则在截止时间结算。
4. 服务端以原子方式应用移动、战斗、资源、模式效果和胜利判定。

服务端会拒绝截止时间后的提交，并返回 `turn_closed`。Agent 迟交的动作仅记录在该客户端的 `expired_actions` 中；不会提交，也不能追溯影响已经结算的回合。连续四次未提交或提交无效动作的玩家将被判负。

#### LLM 计时：30/60 秒窗口

使用 LLM Agent 时，请为服务端配置更大的共享窗口：

```powershell
# 服务端终端：30 秒共享窗口
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 30000
# 服务端终端：较慢的模型或端点使用 60 秒共享窗口
python -m arena_server --host 127.0.0.1 --mode rotation --tick-ms 60000

# LLM Agent 终端：提高请求上限以匹配所选服务端窗口
$env:NEON_ARENA_LLM_TIMEOUT_MS = "24000"  # 配合 --tick-ms 30000
$env:NEON_ARENA_LLM_TIMEOUT_MS = "48000"  # 改为配合 --tick-ms 60000
```

LLM 机器人的请求预算取以下三者中的最小值：`NEON_ARENA_LLM_TIMEOUT_MS`、`tick_ms` 的 80%，以及距离 `reply_by_ms` 剩余时间的 90%。解析失败、HTTP 错误和超时会回退到感知当前模式的启发式策略；使用 `--no-fallback` 时改为等待。任何玩家都不会获得私人延时。

### Web 客户端视觉与操作

所有模式使用相同的动作面板和操作方式；没有模式会增加按钮或改变输入规则。

| 模式 | 可视化 |
| --- | --- |
| `classic` | 标准霓虹棋盘、HP/能量/护盾、分数和节点冷却 |
| `king` | 中心区域覆盖层、目标分数和 `hill_streak` HUD |
| `team` | 队伍配色圆环与边框、队伍 HUD、队伍结果表和获胜成员 |
| `survival` | `mode_state.zone` 外的风暴遮罩、安全区边界、下次收缩提示和 `in_storm` 警报 |
| `bounty` | 指向 `bounty_target` 的虚线、目标标记和 `bounty_streak` |

操作方式：点击或轻触动作及方向；使用 WASD 或方向键移动；按 `1..7` 依次执行移动、冲刺、攻击、采集、护盾、治疗和等待；按 `Space` 等待；按 `Esc` 取消方向选择。刷新后，客户端会使用按服务端隔离的令牌恢复当前大厅、比赛或结算视图。详见 [client/README.md](client/README.md)。

### 观战与回放

从 `agents/` 目录运行：

```powershell
python -m tools.spectator --host 127.0.0.1 --port 7777 --once
python -m tools.spectator --host 127.0.0.1 --port 7777 --plain
python -m tools.spectator --replay ../server/logs/match-example.jsonl --delay 0.2 --plain
```

每份比赛日志包含 `start`、每个已完成回合对应的 `state` 以及 `end`；回合外的即时判负可能额外产生一条 `state` 记录，其 `turn` 和 `events_turn` 均为当前开放的回合。所有记录都包含 `mode` 和 `mode_state`；终端观战器会渲染 `hill_score`、`storm_shrink`、`storm_damage`、`bounty_complete`、`bounty_retarget` 和 `friendly_blocked` 等模式事件。

### 远程部署与安全

- 在可信局域网或 VPN 上，为 Agent 和观战者开放入站 **TCP 7777**，为 HTTP API 开放入站 **TCP 8080**。不要将原始 TCP `7777` 直接暴露给不可信网络。
- 客户端启动器的 **TCP 8090** 应保留在玩家本机；不要将其作为游戏服务端口暴露。
- 客户端和 Agent 都主动建立出站连接，因此不需要入站 NAT 映射。服务端需要可访问的局域网地址、公网 IP 或 VPN/隧道端点。
- 管理员可创建 Windows 防火墙规则：

  ```powershell
  New-NetFirewallRule -DisplayName "NEON ARENA" -Direction Inbound -Protocol TCP -LocalPort 7777,8080 -Action Allow
  ```

- 服务端**没有 TLS**。在不可信网络上，游戏流量、玩家名称和持有者令牌可能被观察或篡改。请使用可信局域网或 VPN。HTTP TLS 反向代理只保护 `8080`，**不会**保护明文 TCP `7777`。远程 TCP Agent 和观战者需要使用 VPN、SSH 隧道/本地端口转发，或能够承载原始 TCP 的 TLS 包装器。由于浏览器混合内容规则，HTTPS 客户端页面无法调用明文 HTTP API。
- CORS 默认为 `*`。生产环境应限制为实际客户端来源。在 `server/` 目录中运行：

  ```powershell
  python -m arena_server --host 0.0.0.0 --cors-origin "http://arena.example.com"
  ```

- HTTP 令牌是会话凭据，不是账户。不要分享给他人。除非网络策略限制访问，否则任何能够连接开放端口的人都可以创建会话或 Agent 连接。
- 服务端根路径、`/client/*` 和未知路径均返回 JSON `404`；服务端从不提供 HTML/CSS/JS。

### 测试与脚本

请在各组件自己的目录中运行对应测试：

```powershell
Set-Location D:\NeonArena\server
python -m unittest discover -s tests -p "test_*.py" -v

Set-Location D:\NeonArena\agents
python -m unittest discover -s tests -v

Set-Location D:\NeonArena\client
python -m unittest discover -s tests -v
node --test

Set-Location D:\NeonArena
python -m unittest discover -s tests -v
```

根目录测试套件包含经典战、占山为王和团队模式的跨进程人类玩家与 Agent 比赛、HTTP 仅返回 JSON 的检查，以及 PowerShell 5.1 编排契约测试。

#### PowerShell 脚本

从仓库根目录运行：

```powershell
# 仅启动服务端；转发端口、计时、人数限制和模式参数
.\scripts\start_server.ps1 -Mode king

# 服务端 + 三个可重新排队的启发式机器人 + 终端观战器
.\scripts\demo.ps1 -Mode rotation
.\scripts\demo.ps1 -Mode king -NoSpectator -OpenClient

# 服务端 + 两个可重新排队的启发式机器人 + Web 客户端启动器
.\scripts\play.ps1 -Mode rotation
.\scripts\play.ps1 -Mode king -NoOpen
```

`start_server.ps1` 默认绑定 `0.0.0.0`，使用 7777/8080 端口、15000 毫秒回合和轮换模式。`demo.ps1` 默认使用回环地址、更快的 1500 毫秒回合、三个机器人和一个观战器。`play.ps1` 默认使用回环地址、两个机器人、面向人类玩家的最低 3 人门槛，以及在 8090 端口启动客户端。`demo.ps1` 和 `play.ps1` 会等待按 Enter，并在 `finally` 块中清理其子进程树。

#### OpenAPI 校验

校验 OpenAPI 文本；如果安装了 PyYAML，再执行解析校验：

```powershell
python -c "import pathlib; p=pathlib.Path('docs/openapi.yaml'); text=p.read_text(encoding='utf-8'); assert '/health' in text and '/actions' in text and 'score_limit' in text and 'mode_state' in text; print('openapi text ok')"
python -c "import yaml, pathlib; d=yaml.safe_load(pathlib.Path('docs/openapi.yaml').read_text(encoding='utf-8')); assert d['openapi'].startswith('3.'); need={'/health','/rules','/sessions','/state','/actions'}; assert need <= set(d['paths']); print('openapi ok')"
```

### 目录结构

```text
D:\NeonArena\
├─ README.md
├─ server\
│  ├─ arena_server\          # authoritative engine, TCP, HTTP, lobby, modes, logs
│  ├─ tests\
│  ├─ README.md
│  └─ logs\                  # generated at runtime
├─ agents\
│  ├─ arena_agent\           # standalone Python SDK and helpers
│  ├─ bots\                  # random, heuristic, LLM
│  ├─ tools\spectator.py     # live terminal viewer and JSONL replay
│  ├─ tests\
│  └─ README.md
├─ client\
│  ├─ index.html
│  ├─ style.css
│  ├─ app.js
│  ├─ launcher.py
│  ├─ tests\
│  └─ README.md
├─ docs\
│  ├─ RULES.md
│  ├─ PROTOCOL.md
│  ├─ HTTP_API.md
│  ├─ openapi.yaml
│  └─ superpowers\           # design/spec/plan history
├─ tests\
│  ├─ test_e2e.py            # real server + TCP Agents + HTTP human
│  └─ test_scripts.py        # PowerShell 5.1 script contracts
└─ scripts\
   ├─ start_server.ps1
   ├─ demo.ps1
   └─ play.ps1
```

### 组件文档

- [服务端运维说明](server/README.md)
- [Agent SDK 与机器人](agents/README.md)
- [Web 客户端指南](client/README.md)
- [游戏规则与模式数值](docs/RULES.md)
- [TCP NDJSON 协议](docs/PROTOCOL.md)
- [HTTP API 与客户端流程](docs/HTTP_API.md)
- [OpenAPI 3.0.3 契约](docs/openapi.yaml)
