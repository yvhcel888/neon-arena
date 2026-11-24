# NEON ARENA 详细设计文档

> 项目：NEON ARENA（霓虹竞技场）——人类与多 Agent 混合的远程回合制竞技游戏
> 版本：v1.0-draft
> 日期：2026-11-23
> 状态：已确认（2026-11-23，评审通过）；实施计划见 `docs/superpowers/plans/2026-11-23-neon-arena.md`
> 项目根目录：`D:\NeonArena`

---

## 0. 结论摘要

NEON ARENA 是一个 **服务端权威、客户端/服务端彻底分离** 的多人网格战术游戏：

- **服务端**（`server/`）只负责游戏逻辑、匹配、状态同步，对外暴露两个网络入口：
  - **Agent 入口**：TCP + NDJSON，默认 `0.0.0.0:7777`
  - **人类/自定义客户端入口**：HTTP + JSON，默认 `0.0.0.0:8080`，前缀 `/api/v1`
- **人类客户端**（`client/`）是完全独立的静态 Web 客户端，由玩家在自己的电脑上启动或托管，通过 HTTP API 连接任意服务器。服务端**不承载、不内嵌、不依赖**客户端页面。
- **Agent**（`agents/`）是独立部署的 Python SDK 与示例机器人，通过 TCP 直连服务器；不导入任何服务端代码。
- 人类与 Agent 进入同一个大厅、同一局比赛，2–4 人自由混战。
- 游戏为 15×15 网格、同时决策/同时结算的回合制竞技：移动、冲刺、攻击、采集、护盾、治疗、等待；最后存活或 80 回合后积分最高者获胜。
- 技术栈：Python 3.10+ 标准库（服务端与 Agent），原生 HTML/CSS/JS（客户端），零第三方依赖、无需构建。

选择“HTTP 轮询 + 原生 JS 客户端”而不是 WebSocket/前端框架，是为了保持 **零依赖、易部署、接口透明**。人类客户端只是 HTTP API 的一个参考实现，任何第三方都可以按文档实现自己的客户端。

---

## 1. 目标与非目标

### 1.1 目标

1. 服务端与客户端分离：两个独立目录、两个独立进程、两套独立部署方式。
2. 支持多个远端 Agent 通过 `IP:端口` 接入并同场竞技。
3. 支持人类玩家通过自己的客户端接入，与 Agent 混合对局。
4. 游戏规则清晰、可测试、可复现（种子、日志、回放）。
5. Agent 接入协议对 LLM/脚本友好：JSON 结构化、状态自描述、错误可恢复。
6. 提供完整的参考实现：服务端、Web 客户端、Agent SDK、3 类示例 Agent、终端观战器。
7. Windows 下开箱即用，同时兼容 Linux/macOS；仅依赖 Python 标准库和现代浏览器。
8. 文档覆盖游戏规则、TCP 协议、HTTP API、部署、防火墙、Agent 开发。

### 1.2 非目标（v1 明确不做）

- 多局并发（同一时刻只有一局，其余排队）。
- 账号系统、排行榜、ELO、持久化档案。
- TLS/HTTPS 终止、OAuth、权限管理（由部署者用反向代理/VPN 解决）。
- 游戏内聊天、表情、语音。
- 组队/阵营模式、战争迷雾。
- 移动端原生 App、Electron 打包。
- 观战 Web UI（v1 提供 TCP 终端观战器）。
- 游戏回放交互式 UI（v1 提供 JSONL 日志和终端回放）。
- 反作弊：游戏没有隐藏信息，Agent 自动化本身就是设计目标。

---

## 2. 顶层架构：客户端与服务端分离

### 2.1 分离原则（硬约束）

| 约束 | 说明 |
|---|---|
| 无共享运行时代码 | `server/`、`agents/`、`client/` 各自可单独复制、单独部署；服务端不得导入客户端/Agent 代码，反之亦然。 |
| 服务端不提供 UI | 服务端 HTTP 端口只返回 JSON（`/api/v1/*`）和健康检查，不返回 HTML/CSS/JS，不读取 `client/` 目录。 |
| 客户端不含游戏逻辑 | 客户端只负责渲染、输入、调用 API；所有合法性、结算、计分由服务端决定。 |
| 协议是唯一契约 | TCP 协议与 HTTP API 由 `docs/` 定义；任何语言都可以实现客户端或 Agent。 |
| 独立部署 | 服务端可运行在云主机/局域网 PC；客户端运行在玩家电脑或任意静态托管；Agent 可运行在第三台机器。 |
| 独立进程 | 三者通过 `IP:端口` 通信，不通过共享内存、文件或本地函数调用。 |

### 2.2 部署视图

```
┌──────────────────────────────┐        HTTP/JSON :8080        ┌─────────────────────────────┐
│  人类玩家电脑                 │  ───────────────────────────▶ │  游戏服务器（任意主机）        │
│  独立 Web 客户端 client/      │  ◀───────────────────────────  │  server/arena_server        │
│  原生 HTML/CSS/JS，无游戏逻辑  │       轮询状态 / 提交动作       │  - 权威游戏引擎               │
└──────────────────────────────┘                               │  - 大厅与匹配                 │
                                                               │  - TCP Agent 网关 :7777      │
┌──────────────────────────────┐        TCP + NDJSON :7777      │  - HTTP API 网关 :8080       │
│  Agent 主机 / 脚本 / LLM      │  ◀───────────────────────────▶ │  - 日志与观战                 │
│  agents/arena_agent + bots   │       推送状态 / 提交动作       └─────────────────────────────┘
└──────────────────────────────┘
```

所有连接都使用 `IP + 端口`：

- Agent → `服务器IP:7777`
- 人类客户端 → `http://服务器IP:8080`（API），客户端页面本身由玩家本地或任意静态站点提供
- 终端观战器 → `服务器IP:7777`（以 spectator 身份）

### 2.3 三个独立产物

| 产物 | 目录 | 运行位置 | 启动方式 | 依赖 |
|---|---|---|---|---|
| 游戏服务端 | `server/` | 服务器/主机 | `python -m arena_server` | Python 3.10+ |
| 参考人类客户端 | `client/` | 玩家电脑或静态托管 | 打开 `index.html`，或用 `launcher.py`（可选，需 Python） | 现代浏览器 |
| Agent SDK + 示例 | `agents/` | Agent 所在机器 | `python -m bots.heuristic ...` | Python 3.10+ |

### 2.4 可替换性

- 自定义客户端：完全按 HTTP API 实现，不依赖参考客户端。
- 自定义 Agent：完全按 TCP 协议实现，可用任意语言；Python 用户可直接复用 `agents/arena_agent`。
- 服务端可以被替换，只要协议兼容；参考客户端和 Agent 不应依赖服务端实现细节。
- 服务端提供 `GET /api/v1/rules` 和 `GET /api/v1/health`，客户端无需硬编码规则或版本号。

---

## 3. 游戏规则

### 3.1 竞技场

| 项目 | 规则 |
|---|---|
| 地图尺寸 | 15×15，四周为墙 |
| 玩家数 | 2–4 人，人类/Agent 可任意混合 |
| 出生点 | 四个内角 `(1,1)`、`(13,1)`、`(1,13)`、`(13,13)`；2 人取一组对角，3/4 人取三角/四角 |
| 能量节点 | 5 个：中心 `(7,7)`，以及 `(7,3)`、`(3,7)`、`(11,7)`、`(7,11)`，初始全部激活 |
| 障碍 | 程序生成，180° 旋转对称，密度约 10%–15% 内部地块，保底全连通 |
| 地图种子 | 每局记录并以 `seed` 下发，可复现 |
| 回合上限 | 80 回合（可由服务端配置） |
| 回合节奏 | 所有存活玩家提交动作或到达截止时间后同时结算，`tick_ms` 默认 15000ms |

出生点与节点位置固定且对称。3 人局只能使用其中三个角，地图是 180° 对称而非 90° 对称，因此 3 人局存在轻微位置差异；通过随机出生分配在统计上平衡，设计接受这一点。

### 3.2 玩家属性

| 属性 | 初始值 | 上限 | 说明 |
|---|---|---|---|
| HP | 100 | 100 | 归零即淘汰 |
| 能量 | 40 | 100 | 释放技能消耗；每回合结束 +4 |
| 护盾 | 0 | 40 | 先于 HP 吸收伤害，不会自然衰减 |
| 分数 | 0 | — | 对 HP 造成 1 点伤害 +1；击杀 +25；采集 +10 |
| 连续漏操作 | 0 | — | 连续 4 回合未提交有效动作则判负 |

### 3.3 行动表

每回合只能选择 **一个** 行动。

| 行动 | 参数 | 能量 | 效果 | 提交时校验 |
|---|---|---:|---|---|
| `move` | `dir` | 0 | 向相邻格移动 1 格 | 目标在界内、不是墙 |
| `dash` | `dir` | 18 | 向同方向移动 2 格 | 两格均在界内、不是墙、能量足够 |
| `attack` | `dir` | 8 | 攻击相邻格；命中造成 22 伤害，护盾优先吸收 | 能量足够 |
| `gather` | — | 0 | 当前格为激活节点时：+30 能量、+10 分，节点进入 4 回合冷却 | 站在激活节点上 |
| `shield` | — | 12 | 护盾 +26，最多 40 | 能量足够且护盾未满 |
| `heal` | — | 25 | HP +25，最多 100 | 能量足够且 HP 未满 |
| `wait` | — | 0 | 不行动 | 始终合法 |

方向 `dir` 仅接受 `n` / `e` / `s` / `w`（北/东/南/西）。

**能量与失败语义**

- 在提交阶段被拒绝的行动不扣能量，Agent 可以在同一回合重新提交。
- 被接受并进入结算的行动，除移动外都会扣除能量；即使冲刺被阻挡、攻击挥空，能量也已经消耗（“出手即消耗”）。
- 采集在提交时检查节点是否激活；节点在回合内只会从激活变为冷却，不会中途激活，因此不会出现已接受但结算失败的采集。
- 治疗/护盾在接受时检查数值上限，结算时按上限截断。

### 3.4 同时结算流程

回合结算严格按以下顺序执行：

1. **锁定动作**：到达截止时间或所有存活玩家都已提交。未提交者使用 `wait`，连续漏操作 +1；提交了有效动作的玩家连续漏操作归零。
2. **扣除能量**：扣除所有被接受行动的能量。
3. **移动阶段**：
   - 冲刺与移动基于 **回合开始时** 的占位计算。
   - 目标格必须是墙外、未被占用，且不能与其他移动者的目标格重复；重复时所有冲突者都不移动。
   - 冲刺的中间格也必须未被占用，且不能是其他移动者的目标格；否则冲刺被阻挡。
   - 不允许交换位置（因为目标格必须初始为空），不允许穿过玩家。
   - 移动/冲刺被阻挡不会扣 HP，冲刺能量已扣。
4. **非移动效果**：护盾、治疗、采集生效（这些玩家本回合没有移动）。护盾在随后同回合的战斗中即可吸收伤害。
5. **战斗阶段**：用 **移动后的位置** 判定攻击。所有攻击同时生效；即使攻击者在同一阶段受到致命伤害，其攻击仍然命中。伤害先扣护盾，再扣 HP。
6. **死亡判定**：HP ≤ 0 的玩家淘汰。击杀归属为本回合对该目标造成 HP 伤害最多的攻击者；并列时玩家 ID 较小者获得击杀分。
7. **能量恢复与节点冷却**：存活玩家 +4 能量（上限 100）；所有冷却中节点 -1。
8. **漏操作判负**：连续漏操作达到 4 的玩家立即判负（视为淘汰，无击杀者）。
9. **胜负检查**：满足结束条件则结束，否则回合数 +1，进入下一回合。

因此：**走出攻击范围可以躲开近战；走进范围可以发起攻击；护盾/治疗在本回合战斗前生效；同归于尽可能发生。**

### 3.5 伤害、击杀与计分

- 攻击基础伤害 22，护盾先吸收；护盾伤害不计分，只有实际扣 HP 的伤害计分。
- 击杀 +25；本回合造成最多 HP 伤害者获得击杀归属。
- 采集 +10，无论能量是否溢出。
- 不设生存分；分数只来自伤害、击杀、采集。

### 3.6 胜负与排名

结束时按以下优先级判定：

1. **最后存活**：结算后仅 1 名存活玩家，该玩家获胜（`reason = last_standing`）。
2. **同时团灭**：0 名存活玩家，按最终排名第一者获胜（`reason = mutual_destruction`）。
3. **回合耗尽**：回合上限结算完毕仍有 ≥2 人存活，按排名第一者获胜（`reason = turn_limit`）。
4. **服务端异常中止**：`reason = aborted`，不设获胜者，保留排名与日志。

排名规则（从高到低）：存活优先 → 分数 → HP → 能量 → 玩家 ID 升序。玩家 ID 在每个对局内为 `P1`–`P4`，在开局时按大厅排队顺序分配。

### 3.7 节点冷却

- 采集后节点 `cooldown = 4`，本回合结束 -1。
- 节点在 `cooldown = 0` 时可再次采集；从采集回合算起，第 4 个后续回合恢复可用。
- 节点状态对所有人可见（本游戏没有战争迷雾）。

### 3.8 地图生成

1. 以服务端种子初始化伪随机数生成器。
2. 保留边界墙、四个出生点 3×3 保护区、五个节点及其相邻格。
3. 在 180° 旋转等价的地块对中随机放置障碍，目标密度 10%–15%。
4. 用 BFS 检查四个出生点与五个节点是否处在同一连通区域。
5. 不连通则重新生成，最多 100 次；仍失败则退回无内部障碍的空场。
6. 记录最终 `seed`；相同 seed 必须生成相同地图。

### 3.9 回合节奏与超时

- 服务端广播状态时给出绝对截止时间 `reply_by_ms`（Unix 毫秒）。
- 默认 `tick_ms = 15000`。这只是 **最长等待**：所有存活玩家都提交后会立即结算（不早于 `min_turn_ms = 250` 毫秒，保证观战可读）。
- Agent 通常瞬间提交，但人类玩家仍需等待所有人；因此快速 Bot 不会催促人类。
- 人类客户端显示倒计时，提交后显示“等待其他玩家”。
- 超时未提交 → 本回合按 `wait` 处理，连续 4 次判负。
- 同一回合可以重复提交，最后一次通过校验的动作生效；旧回合的提交返回 `stale_turn`。

### 3.10 大厅与匹配

- 单服务器同一时刻只进行一局比赛，其余玩家排队。
- 大厅最少 2 人、最多 4 人。
- 等待人数首次达到 2 人时开始 `lobby_wait_ms`（默认 5000ms）倒计时；第 4 人加入时立即开局。
- 倒计时期间人数掉到 2 以下则取消；有新玩家加入不重置倒计时。
- 开局取排队最久的至多 4 人；多余玩家留在大厅继续等待。
- 对局结束后，所有参赛者回到 **空闲** 状态，不会自动重新排队；玩家/Agent 需重新发送加入请求。这样可避免无人值守 Bot 无限连赛，也给人类时间看结算。
- 参赛者在对局中断线：立即判负（forfeit）：`alive=false`、`hp=0`、`stats.forfeited=true`，无击杀者。其余玩家继续。
- 人类 HTTP 会话在比赛中关闭页面不会立刻判负，但会因连续超时在 4 回合后判负；大厅中的 HTTP 会话 30 秒无轮询会被清理，避免占位。

---

## 4. 服务端设计

### 4.1 模块划分

`server/arena_server/` 内部划分：

| 模块 | 职责 | 依赖 |
|---|---|---|
| `config.py` | 配置数据类、命令行参数、规则常量 | 标准库 |
| `engine.py` | 纯游戏引擎：地图、玩家、动作校验、结算、计分、状态序列化 | `config` |
| `protocol.py` | TCP 消息构造、错误码、协议版本 | 标准库 |
| `lobby.py` | 大厅队列、倒计时、开赛决策 | `engine` 的玩家模型 |
| `match.py` | 单局生命周期：状态广播、动作收集、计时、结算、结束 | `engine`, `protocol` |
| `tcp_gateway.py` | asyncio TCP 连接、NDJSON 编解码、连接生命周期 | `protocol`, `lobby`, `match` |
| `http_api.py` | 独立 HTTP/JSON API、CORS、会话令牌、轮询视图 | `protocol`, `lobby`, `match` |
| `sessions.py` | HTTP 会话、令牌、清理 | 标准库 |
| `logging_utils.py` | 服务日志与 JSONL 对局日志 | 标准库 |
| `server.py` | 组装各组件、启动/关闭、信号处理 | 全部 |
| `__main__.py` | CLI 入口 | `server` |

约束：`engine.py` 不直接做网络 I/O；`http_api.py` 与 `tcp_gateway.py` 不复制游戏规则。

### 4.2 并发模型

- 单个 asyncio 事件循环，所有游戏状态只在循环线程内修改。
- 不使用线程池、不共享跨线程可变状态。
- TCP 每连接一个读协程 + 一个写队列协程；HTTP 每请求一个短连接协程。
- 人类客户端轮询不维持长连接；动作通过 `POST` 进入同一事件循环。
- 单局最多 4 人、总连接数上限 32，性能压力可忽略。
- 写操作采用每连接 `asyncio.Queue` 串行化，避免并发写坏 NDJSON 行。

### 4.3 参与者模型

服务端内部统一表示参与者：

```
Participant
  - internal_id        内部唯一 ID（不对外）
  - name               显示名
  - kind               "agent" | "human"
  - transport          "tcp" | "http"
  - tcp_client         TCP 连接对象（可空）
  - http_session       HTTP 会话对象（可空）
  - state              "lobby" | "playing" | "idle"
  - match              Match 引用（可空）
  - missed_turns       连续漏操作次数
  - joined_at          排队时间
```

- 人类通过 `POST /api/v1/sessions` 创建 `Participant` 与 HTTP 会话。
- Agent 通过 TCP `join` 创建 `Participant`。
- 两者进入同一 `LobbyManager` 队列，对局内不做区分，只在 `kind` 字段上展示。
- 对局开始时分配公共玩家 ID `P1`–`P4`（按排队顺序），并写入参与者。下一局重新分配。
- 大厅列表仅暴露 `name` 和 `kind`；玩家 ID 在 `start`/`state` 中才出现。

### 4.4 大厅状态机

```
IDLE ──join──▶ LOBBY(1人) ──join──▶ LOBBY(≥2人, countdown)
                  ▲                       │
                  │                       ├─人数<2────▶ LOBBY(1人) 取消计时
                  │                       ├─人数=4────▶ START 立即
                  │                       └─计时结束──▶ START
                  │
                  └────────match end───────┘（参赛者进入 idle，不自动排队）
```

- 大厅广播在每次队列变化、倒计时变化、开赛时发送。
- 开赛时从队列头部取至多 4 人；队列继承剩余玩家。
- 只有一场活动对局；大厅中的新玩家必须等当前对局结束。
- 观战者在无对局时接收大厅广播；有对局时立即收到快照（见 5.3 / 5.4）。

### 4.5 对局生命周期

1. 生成 `match_id`、种子、地图、玩家 ID、出生点。
2. 写入 JSONL 日志头；向所有参赛者和观战者发送 `start`。
3. 循环：
   - 构造本回合状态与 `reply_by_ms`（当前时间 + `tick_ms`）；
   - 推送 `state`（TCP）并更新 HTTP 会话可轮询快照；
   - 等待所有存活参与者提交或超时（最早在 `min_turn_ms` 后结算）；
   - 锁定动作，填充 `wait`，更新漏操作计数；
   - 调用引擎结算；
   - 写入日志，检查结束条件。
4. 结束：发送 `end`（包含最终排名和最后一回合事件），保存日志，释放参与者，启动大厅计时。
5. 清理：TCP 参赛连接保持打开，允许 Agent 重新 `join`；HTTP 会话保留令牌和结果，允许重新排队。

若引擎抛出未捕获异常：记录完整堆栈，向双方发送 `reason = aborted` 的 `end`，对局终止，服务端继续运行。

### 4.6 并发输入与竞态

- TCP 动作和 HTTP 动作都调用同一个 `Match.submit(participant, action)`，在事件循环内串行执行。
- `submit` 立即做结构/资源校验；通过则写入该参与者的 pending action 并发送确认。
- 结算开始后锁住回合：之后到达的提交返回 `stale_turn` 或 `turn_closed`。
- 重复提交：同一回合最后一次合法提交生效。
- 超时后未提交者按 `wait` 处理，不需要额外消息。
- 玩家在提交后被淘汰：pending action 被丢弃，不参与结算。

### 4.7 断线与清理

- TCP 连接断开：若在比赛中，立即 `forfeit`；若在大厅，移除并广播；若仅为观战，移除。
- HTTP 会话：
  - `DELETE /api/v1/sessions` 主动离开并作废令牌。
  - 大厅中 30 秒无轮询 → 清理会话。
  - 比赛中无轮询不会立即判负，依赖 4 次连续超时。
  - 比赛结束后保留会话与结算视图 600 秒；期间可带 token 重新排队，超时清理。
- 未 `join` 的 TCP 连接 120 秒无消息 → 关闭。
- 连接/会话上限 32；超出时 HTTP 返回 503，TCP 发送 `server_full` 并关闭。

### 4.8 可观测性

- 控制台日志（INFO）：监听地址、加入/离开、开局（玩家、种子）、结束（获胜者、回合数）、异常。
- `--verbose`（DEBUG）：每回合结算事件摘要、动作拒绝原因。
- JSONL 对局日志：每局一个文件，含 `start`、每回合 `state`、`end`，可直接用于回放/分析。
- 服务端不在日志中记录 HTTP 令牌或 Agent 的 Authorization 头。
- `GET /api/v1/health` 暴露运行状态，供脚本判活。

---

## 5. TCP Agent 协议（默认端口 7777）

### 5.1 传输约定

- UTF-8 文本，一行一个 JSON 对象（NDJSON），以 `\n` 分隔。
- 最大单行 64 KiB；超限断开连接。
- 所有消息必须是 JSON object，必须包含字符串字段 `type`。
- 协议版本 `1`。`welcome` 和 `join` 都携带/校验版本。
- 服务端主动推送，客户端必须持续读取；不要依赖请求-响应严格配对（`action_ack` 是异步的）。
- 客户端发送的未知消息类型返回 `error`，不断开。

### 5.2 消息总览

| 方向 | 类型 | 用途 |
|---|---|---|
| S→C | `welcome` | 连接建立，告知协议版本和连接 ID |
| C→S | `join` | 以玩家身份加入大厅 |
| S→C | `joined` | 加入成功，返回最终显示名 |
| S→C | `lobby` | 大厅玩家与倒计时 |
| C→S | `spectate` | 以观战者身份订阅 |
| S→C | `spectating` | 观战订阅成功 |
| C→S | `action` | 提交本回合动作 |
| S→C | `action_ack` | 动作已被接受 |
| S→C | `start` | 对局开始，含完整规则/地图/玩家 |
| S→C | `state` | 每回合开始的状态 + 上一回合事件 |
| S→C | `end` | 对局结束、排名 |
| C→S | `leave` | 离开大厅或比赛中判负 |
| S→C | `left` | 离开确认 |
| C→S | `ping` | 心跳 |
| S→C | `pong` | 心跳响应 |
| S→C | `error` | 错误说明，连接通常保持 |

### 5.3 连接与大厅

服务端在连接建立后立即发送：

```json
{"type":"welcome","server":"Neon Arena","protocol":1,"client_id":"c-7f3a"}
```

加入大厅：

```json
{"type":"join","protocol":1,"name":"Alpha"}
```

成功响应（最终名字可能因重名追加 `-2`）：

```json
{"type":"joined","protocol":1,"name":"Alpha","kind":"agent"}
```

`join` 规则：

- 名称 1–20 个字符；去除首尾空白；拒绝控制字符。
- 重名自动追加 `-2`、`-3`，以 `joined.name` 为准。
- 已在比赛/大厅中的连接再次 `join` 返回 `already_joined`。
- 对局结束后的连接可再次 `join` 重新排队。
- `protocol` 不匹配返回 `protocol_mismatch` 并保持连接。

大厅广播：

```json
{
  "type": "lobby",
  "players": [
    {"name": "Alpha", "kind": "agent"},
    {"name": "Alice", "kind": "human"}
  ],
  "min_players": 2,
  "max_players": 4,
  "starts_in_ms": 4200
}
```

`starts_in_ms` 在不足 2 人时为 `null`；4 人时即将开局，值可能为 0。

`leave` 响应：

```json
{"type":"left"}
```

比赛中 `leave` 等于认输，随后仍会收到该局的 `end`。

观战：

```json
{"type":"spectate"}
```

响应：

```json
{"type":"spectating","match_running":true}
```

- 若正在比赛，紧接着补发不含 `you` 的 `start` 和当前回合的 `state`；若在大厅，则持续接收大厅广播，开赛后接收 `start`。
- 观战者不占玩家席位、不提交动作；`join` 与 `spectate` 互斥。
- 观战者断开不产生 `forfeit`，比赛不受影响。

### 5.4 对局开始

`start` 是每局完整的静态信息，参赛者的消息带 `you` 字段：

```json
{
  "type": "start",
  "protocol": 1,
  "match_id": "m-20261123-142501-a1b2",
  "seed": 74128831,
  "tick_ms": 15000,
  "min_turn_ms": 250,
  "turn_limit": 80,
  "rules": {
    "max_hp": 100,
    "max_energy": 100,
    "start_energy": 40,
    "energy_regen": 4,
    "attack": {"cost": 8, "damage": 22},
    "dash": {"cost": 18, "distance": 2},
    "heal": {"cost": 25, "amount": 25},
    "shield": {"cost": 12, "amount": 26, "max": 40},
    "gather": {"energy": 30, "node_cooldown": 4},
    "score": {"damage": 1, "kill": 25, "gather": 10},
    "turn_limit": 80
  },
  "arena": {
    "width": 15,
    "height": 15,
    "walls": [[3, 2], [11, 12]],
    "nodes": [[7, 3], [7, 7], [11, 7], [7, 11], [3, 7]],
    "spawns": [[1, 1], [13, 13], [13, 1], [1, 13]]
  },
  "players": [
    {"id": "P1", "name": "Alpha", "kind": "agent", "pos": [1, 1]},
    {"id": "P2", "name": "Alice", "kind": "human", "pos": [13, 13]}
  ],
  "you": "P1"
}
```

- `walls` 和 `nodes` 是 `[x, y]` 坐标，原点左上角，x 向右，y 向下。
- 观战者的 `start` 不含 `you`。
- 新观战者中途接入时，服务端补发 `start` 和当前回合的 `state`。
- `rules` 是规则数值的唯一权威；客户端不应硬编码。

### 5.5 回合状态

```json
{
  "type": "state",
  "match_id": "m-20261123-142501-a1b2",
  "turn": 6,
  "turn_limit": 80,
  "reply_by_ms": 1763890000000,
  "players": [
    {
      "id": "P1",
      "name": "Alpha",
      "kind": "agent",
      "pos": [3, 4],
      "hp": 78,
      "shield": 0,
      "energy": 40,
      "score": 12,
      "alive": true,
      "stats": {
        "damage_dealt": 12,
        "kills": 0,
        "gathered": 0,
        "forfeited": false
      }
    }
  ],
  "nodes": [
    {"pos": [7, 7], "cooldown": 0, "active": true},
    {"pos": [3, 7], "cooldown": 2, "active": false}
  ],
  "events_turn": 5,
  "events": [
    {"type": "move", "player": "P1", "from": [2, 4], "to": [3, 4]},
    {"type": "attack", "player": "P2", "dir": "w", "target": [7, 9]},
    {"type": "damage", "player": "P2", "target": "P1", "hp_damage": 22, "shield_damage": 0}
  ],
  "you": "P1"
}
```

- `events` 是 **上一回合** 的结算事件；第一回合为空数组，`events_turn = 0`。
- 对局在最后一回合结束后直接发送 `end`，不再发送下一回合状态；最后一回合事件在 `end.events` 中。
- 死亡玩家仍收到 `state`（可观看），但动作会被拒绝。
- 参赛者以 `you` 识别自己；观战者没有 `you`。
- `reply_by_ms` 是绝对时间，用于倒计时；客户端不应信任本地时钟与服务器一致，可结合延迟估算。

### 5.6 动作提交

```json
{"type":"action","turn":6,"action":{"type":"move","dir":"n"}}
```

成功：

```json
{"type":"action_ack","turn":6,"action":{"type":"move","dir":"n"}}
```

- `action` 必须带当前 `turn`；不匹配返回 `stale_turn`。
- 同一回合可多次提交，最后一次合法动作覆盖。
- 结算后才到达的提交返回 `turn_closed`。
- 被拒绝的动作不消耗资源，可立即重试。

动作语法：

```json
[
  {"type": "move", "dir": "n|e|s|w"},
  {"type": "dash", "dir": "n|e|s|w"},
  {"type": "attack", "dir": "n|e|s|w"},
  {"type": "gather"},
  {"type": "shield"},
  {"type": "heal"},
  {"type": "wait"}
]
```

### 5.7 结算事件

| type | 字段 | 含义 |
|---|---|---|
| `move` | `player, from, to` | 成功移动 |
| `dash` | `player, from, to` | 成功冲刺 |
| `blocked` | `player, action, dir, reason` | 移动/冲刺被阻挡，`reason` ∈ `occupied/collision` |
| `attack` | `player, dir, target` | 发起攻击（target 可能为空） |
| `damage` | `player, target, hp_damage, shield_damage` | 攻击命中 |
| `heal` | `player, amount, hp` | 治疗 |
| `shield` | `player, amount, shield` | 获得护盾 |
| `gather` | `player, pos, energy_gain, score_gain` | 采集成功 |
| `death` | `player, killer` | 淘汰；`killer` 可为 null |
| `forfeit` | `player` | 认输/断线/连续超时判负 |

事件按结算阶段顺序排列，便于观战还原。

### 5.8 结束消息

```json
{
  "type": "end",
  "match_id": "m-20261123-142501-a1b2",
  "reason": "last_standing",
  "turns": 37,
  "winner": {"id": "P2", "name": "Alice"},
  "standings": [
    {
      "id": "P2", "name": "Alice", "kind": "human", "pos": [8, 9],
      "hp": 41, "shield": 0, "energy": 26, "score": 84, "alive": true,
      "stats": {"damage_dealt": 66, "kills": 2, "gathered": 1, "forfeited": false}
    }
  ],
  "events_turn": 37,
  "events": [
    {"type": "death", "player": "P1", "killer": "P2"}
  ]
}
```

- `reason` ∈ `last_standing` / `mutual_destruction` / `turn_limit` / `aborted`。
- 结束后连接保持，玩家可以再次 `join`。HTTP 会话可重新排队。
- `standings` 使用与 `players` 相同的字段结构。

### 5.9 错误

```json
{"type":"error","code":"invalid_action","message":"not enough energy for attack","turn":6}
```

| code | 说明 |
|---|---|
| `bad_json` | 行不是合法 JSON |
| `invalid_message` | 缺少 `type` 或字段类型错误 |
| `protocol_mismatch` | 协议版本不支持 |
| `invalid_name` | 名字为空/过长/含控制字符 |
| `already_joined` | 已经在大厅或比赛中 |
| `not_joined` | 尚未 join 就提交动作 |
| `not_in_match` | 不在比赛中 |
| `not_alive` | 已被淘汰，不能再行动 |
| `stale_turn` | `turn` 不是当前决策回合 |
| `turn_closed` | 本回合已结算 |
| `invalid_action` | 动作语法/资源/位置校验失败（message 说明原因） |
| `server_full` | 连接数/会话数已满 |
| `rate_limited` | 消息频率超限 |
| `internal_error` | 服务端异常 |

### 5.10 心跳与限流

- `{"type":"ping","ts":123}` → `{"type":"pong","ts":123}`，用于保活/测延迟。
- 每个 TCP 连接 30 条消息/秒的令牌桶；超限返回 `rate_limited`，可继续使用。
- 未加入且 120 秒无任何消息的连接关闭。
- 协议不要求应用层心跳，但长连接建议每 30 秒 ping 一次。

### 5.11 完整时序示例

```
S→C welcome
C→S join Alpha
S→C joined Alpha
S→C lobby [Alpha] starts_in_ms=null
C→S join 无效重复 → error already_joined
（Alice 通过 HTTP 加入）
S→C lobby [Alpha, Alice] starts_in_ms=4800
... 倒计时结束
S→C start ... you=P1
S→C state turn=1 events=[]
C→S action turn=1 move e
S→C action_ack turn=1
... 结算后
S→C state turn=2 events=[move]
...
S→C end ...
```

---

## 6. HTTP API（人类客户端 / 自定义客户端）

### 6.1 基本约定

- 基础地址：`http://<server-ip>:8080/api/v1`
- 请求和响应均为 `application/json; charset=utf-8`
- 人类会话使用 Bearer Token：`Authorization: Bearer <token>`
- 无 Cookie、无服务器端浏览器会话；token 由 `POST /sessions` 返回
- 服务端 **不提供任何 HTML/JS/CSS**；根路径返回 404 JSON
- API 版本在 URL 中；TCP 协议版本在消息中
- 所有响应统一外层格式：
  - 成功：`{"ok": true, ...}`
  - 失败：`{"ok": false, "error": {"code": "...", "message": "..."}}`
- HTTP 状态码：
  - `200` 成功
  - `400` 请求体/动作非法
  - `401` token 缺失或无效
  - `404` 路径不存在
  - `409` 回合已关闭/不在比赛中/重复操作
  - `429` 频率限制
  - `500` 服务端异常
  - `503` 服务器满员

### 6.2 CORS（客户端独立部署的关键）

参考客户端可能运行在 `http://127.0.0.1:8090`、`file://` 或任意静态站点，因此 API 默认允许跨域：

- `Access-Control-Allow-Origin: *`（默认；可通过 `--cors-origin` 收紧）
- `Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS`
- `Access-Control-Allow-Headers: Authorization, Content-Type`
- `Access-Control-Max-Age: 600`
- 正确处理 `OPTIONS` 预检，返回 `204`
- 不使用 `Access-Control-Allow-Credentials`，因为不使用 Cookie
- 错误响应同样带 CORS 头

`*` 意味着任何网页都能访问 API；加入游戏仍需自行创建会话，token 保存在玩家客户端。对公网部署的滥用风险通过连接数上限、频率限制和网络层访问控制缓解。生产环境建议用 `--cors-origin` 指定自己的客户端源。

### 6.3 端点

#### GET /api/v1/health

无需鉴权。

```json
{
  "ok": true,
  "server": "Neon Arena",
  "version": "1.0.0",
  "protocol": 1,
  "uptime_s": 3721,
  "lobby_players": 2,
  "match_running": true,
  "active_players": 3,
  "spectators": 1
}
```

#### GET /api/v1/rules

无需鉴权，供自定义客户端在加入前展示规则。

```json
{
  "ok": true,
  "protocol": 1,
  "rules": { "...": "与 start.rules 相同" },
  "defaults": {
    "tick_ms": 15000,
    "min_turn_ms": 250,
    "turn_limit": 80,
    "min_players": 2,
    "max_players": 4
  }
}
```

#### POST /api/v1/sessions

创建或恢复人类会话，并加入大厅。

新建请求（无 Authorization）：

```json
{"name": "Alice"}
```

恢复请求（带已有 token；body 可为空）：

```
Authorization: Bearer <token>
```

响应：

```json
{
  "ok": true,
  "token": "qt9x...（仅创建/恢复时返回）",
  "view": { "...": "state view，见 6.4" }
}
```

行为：

- 新 token，创建 `kind=human` 的参与者并排队。
- 带合法 token：若会话在大厅/比赛中，幂等返回当前视图；若在 `ended`/空闲状态，则重新排队。
- 比赛结束后的会话与结算视图保留 600 秒，期间可用原 token 重新排队。
- 带非法 token 且提供 `name`：视为新会话（客户端应清理旧 token）；无 `name` 返回 401。
- 名字规则与 TCP 相同，重名自动加后缀；以 `view.you.name` 为准。
- 服务器满员返回 503 `server_full`。

#### GET /api/v1/state

需要 `Authorization: Bearer <token>`。

响应：

```json
{"ok": true, "view": { "...": "见 6.4" }}
```

客户端建议轮询间隔：

- 大厅：800ms
- 比赛中：350ms
- 页面隐藏：1500ms（继续轮询，避免漏掉回合；但无法代替提交动作）
- 网络错误：指数退避，最大 5s，并在 UI 显示“重连中”

#### POST /api/v1/actions

需要 token。

```json
{"turn": 6, "action": {"type": "attack", "dir": "e"}}
```

成功：

```json
{"ok": true, "turn": 6, "action": {"type": "attack", "dir": "e"}}
```

失败示例：

```json
{
  "ok": false,
  "error": {"code": "insufficient_energy", "message": "attack requires 8 energy, have 6"}
}
```

- `turn` 必须等于当前决策回合，否则 409 `stale_turn`。
- 同一回合可重复提交，最后合法者生效。
- 已结算后提交返回 409 `turn_closed`。
- 被拒绝的动作不扣资源，可重试。

#### DELETE /api/v1/sessions

需要 token。主动离开：

- 在大厅：从队列移除，广播新大厅。
- 在比赛：立即判负（forfeit）。
- 之后 token 作废，返回 `{"ok": true}`。
- 客户端清理本地 token，回到连接页。

#### OPTIONS /api/v1/*

返回 CORS 预检响应，`204`，无业务逻辑。

### 6.4 状态视图（view）

这是参考客户端唯一需要理解的响应结构。服务端保证字段稳定。

大厅：

```json
{
  "mode": "lobby",
  "you": {"id": null, "name": "Alice", "kind": "human"},
  "server": {"version": "1.0.0", "protocol": 1, "now_ms": 1763890000000},
  "lobby": {
    "players": [
      {"name": "Alpha", "kind": "agent"},
      {"name": "Alice", "kind": "human"}
    ],
    "min_players": 2,
    "max_players": 4,
    "starts_in_ms": 4200
  },
  "match": null,
  "result": null
}
```

比赛：

```json
{
  "mode": "match",
  "you": {"id": "P2", "name": "Alice", "kind": "human"},
  "server": {"version": "1.0.0", "protocol": 1, "now_ms": 1763890000000},
  "lobby": null,
  "match": {
    "match_id": "m-20261123-142501-a1b2",
    "seed": 74128831,
    "turn": 6,
    "turn_limit": 80,
    "tick_ms": 15000,
    "reply_by_ms": 1763890015000,
    "rules": { "...": "与 TCP start.rules 相同" },
    "arena": { "...": "与 TCP start.arena 相同" },
    "players": [ "...与 TCP state.players 相同" ],
    "nodes": [ "...与 TCP state.nodes 相同" ],
    "events_turn": 5,
    "events": [ "...与 TCP state.events 相同" ],
    "submitted": false,
    "your_action": null
  },
  "result": null
}
```

结束：

```json
{
  "mode": "ended",
  "you": {"id": "P2", "name": "Alice", "kind": "human"},
  "server": { "...": "..." },
  "lobby": null,
  "match": { "...": "最后一回合的冻结视图" },
  "result": {
    "match_id": "m-20261123-142501-a1b2",
    "reason": "last_standing",
    "turns": 37,
    "winner": {"id": "P2", "name": "Alice"},
    "standings": [ "...玩家对象..." ],
    "events_turn": 37,
    "events": [ "...最后一回合事件..." ]
  }
}
```

- `mode` ∈ `lobby` / `match` / `ended`。
- `you.id` 在大厅中为 `null`，开局后分配为 `P1`–`P4`。
- `submitted` 表示当前回合是否已有玩家动作处于待结算状态；`your_action` 回显该动作。
- 回合切换后 `submitted` 重置为 `false`。
- 客户端可以通过 `reply_by_ms` 与 `server.now_ms` 计算剩余时间，避免依赖本地时钟。
- 结束视图保留 `match` 快照，便于在结算界面继续绘制最终棋盘。

### 6.5 错误码

HTTP 错误码与 TCP 共享语义，另有传输层码：

| code | HTTP | 说明 |
|---|---|---|
| `invalid_json` | 400 | 请求体不是 JSON |
| `invalid_name` | 400 | 名字非法 |
| `invalid_action` | 400 | 动作结构非法 |
| `insufficient_energy` | 400 | 能量不足 |
| `out_of_bounds` / `wall` | 400 | 移动目标非法 |
| `no_active_node` | 400 | 采集位置无激活节点 |
| `full_hp` / `shield_full` | 400 | 治疗/护盾目标已达上限 |
| `unauthorized` | 401 | token 无效 |
| `stale_turn` / `turn_closed` | 409 | 回合不匹配/已关闭 |
| `not_in_match` / `not_alive` | 409 | 当前状态不能行动 |
| `rate_limited` | 429 | 频率限制 |
| `server_full` | 503 | 满员 |
| `internal_error` | 500 | 服务端异常 |

### 6.6 客户端接入流程示例

```
1. GET  /api/v1/health                 确认服务端可达
2. POST /api/v1/sessions {"name":...}  获得 token
3. GET  /api/v1/state                  轮询大厅
   （人数足够，服务端倒计时开局）
4. GET  /api/v1/state                  mode=match，拿到规则/地图/状态
5. POST /api/v1/actions                每回合提交一次
6. GET  /api/v1/state                  轮询下一回合与事件
7. GET  /api/v1/state                  mode=ended，展示排名
8. POST /api/v1/sessions（带 token）    再来一局；或 DELETE 离开
```

### 6.7 OpenAPI

`docs/openapi.yaml` 提供 OpenAPI 3.0 描述，覆盖以上端点、view schema 和错误结构。第三方客户端可以据此生成类型或代码。

### 6.8 HTTP 实现约束

- 自行实现极简 asyncio HTTP/1.1 解析，只支持 `GET/POST/DELETE/OPTIONS`；请求体必须带 `Content-Length`，不支持 chunked。
- 请求头上限 16 KiB，请求体上限 32 KiB；超过返回 413/431 并关闭。
- 响应带 `Content-Length`，`Connection: close`（轮询场景无需 keep-alive）。
- 无访问日志，避免记录 token；错误日志也不记录 Authorization 值。
- 每个会话限 20 请求/秒（令牌桶）；超过返回 429。
- 非 `/api/v1/*` 路径返回 404 JSON；不提供目录遍历，不读取客户端文件。
- `--api-port 0` 由系统分配端口（测试用）；端口冲突时启动失败并明确报错。

---

## 7. 参考人类客户端（client/）

### 7.1 独立形态

- 纯静态：`index.html` + `style.css` + `app.js`，无构建、无 CDN、无第三方库。
- 玩家可：
  1. 运行 `python launcher.py`（推荐，默认 `http://127.0.0.1:8090`，可传 `--server http://host:8080` 预设服务器地址）；
  2. 将 `client/` 部署到任意静态托管；
  3. 直接打开 `index.html`（部分浏览器对 `file://` 的 fetch/localStorage 有限制，不保证；首选本地 launcher）。
- 连接页必须允许手动输入 **服务器地址**（IP + 端口），默认 `http://127.0.0.1:8080`；不可把服务端地址硬编码为同源。
- 客户端按 URL 存储 token：切换服务器时清理旧 token。

### 7.2 页面结构

1. **连接页**
   - 标题、简短规则、名字输入、服务器地址输入、连接按钮。
   - 显示健康检查结果与错误（无法连接、版本不兼容、服务器满员）。
2. **大厅页**
   - 已连接玩家列表，标识 human/agent。
   - 人数、倒计时、规则速览、离开按钮。
3. **对局页**
   - 顶栏：回合 / 上限、倒计时进度条、自己的分数。
   - 中央：Canvas 棋盘（自适应、DPR 缩放）。
   - 侧栏：自己的 HP/能量/护盾、玩家排名条、最近事件流。
   - 底部/侧边：动作面板与方向键（移动端友好）。
   - 状态提示：已提交/等待中/已淘汰/重连中。
4. **结算页**
   - 胜者、排名、分数、伤害/击杀/采集统计。
   - “再来一局”（带 token 重新排队）、“离开”。

### 7.3 操作

- 动作区按钮：移动、冲刺、攻击、采集、护盾、治疗、等待。
- 方向选择：方向键或 WASD；屏幕 D-pad（移动端）。
- 选择“移动/冲刺/攻击”后按方向键立即提交；采集/护盾/治疗/等待直接提交。
- 键盘：
  - `W/A/S/D` 或方向键：移动；
  - `1` 移动、`2` 冲刺、`3` 攻击、`4` 采集、`5` 护盾、`6` 治疗、`7` 等待；
  - `Esc` 取消方向模式；`Space` 等待。
- 提交后锁定本回合输入，直到收到新回合或服务器拒绝（拒绝则解锁重试）。
- 客户端仅做体验层禁用（能量不足变灰），最终校验以服务端为准。
- 死亡后禁用操作，允许继续观战至结算。

### 7.4 渲染与视觉

- 深色霓虹风格：背景 `#070b14`，网格线低亮青色，墙为深色块+霓虹边。
- 玩家配色：P1 青、P2 品红、P3 亮绿、P4 琥珀；同时用玩家首字母区分，避免只靠颜色。
- 玩家：圆形本体、HP 条、能量环、护盾外环；自己带脉冲高亮圈。
- 节点：菱形/六边形，激活时发光，冷却时显示数字。
- 事件流用文本展示最近 25 条事件，不堆叠弹窗。
- 支持 `prefers-reduced-motion`，减少脉冲/扫描线动画。
- 响应式：桌面左右布局；窄屏棋盘在上、状态与操作在下。
- 所有名称用 `textContent` 渲染，禁止 `innerHTML` 拼接用户输入；无外部字体与图片依赖。

### 7.5 状态与重连

- 启动时读取 `localStorage`：
  - 服务器地址；
  - 与该地址绑定的 token。
- 若有 token：先 `GET /state`，成功则恢复大厅/对局/结算；401 则清理并回到连接页。
- 页面刷新不会丢局；服务器端会话仍在。
- 网络断开：显示“重连中”，指数退避重试；token 仍有效时自动恢复。
- 服务器重启：token 无效，提示重新加入。
- 只创建一次轮询循环；避免重复定时器。
- 提交动作后立即将本地 `submitted` 置为 true，并等待轮询确认；409 时强制刷新状态。

### 7.6 本地启动器 launcher.py

- 仅标准库，默认只监听 `127.0.0.1`，避免把客户端目录暴露到局域网。
- 参数：
  - `--host 127.0.0.1`
  - `--port 8090`
  - `--server http://127.0.0.1:8080`（生成带 `?server=` 的打开地址）
  - `--no-open`
- 只服务 `client/` 内的文件；路径白名单，防目录遍历。
- 不代理 API、不接触游戏状态，纯静态文件服务器。
- 可选：直接双击 HTML 或使用任意静态托管。

### 7.7 独立客户端的限制

- 浏览器从 HTTPS 页面请求 HTTP API 会被混合内容策略阻止。对公网部署：要么客户端也走本地 HTTP/或 HTTP 站点，要么给服务端套 HTTPS 反向代理。
- 客户端不做本地游戏模拟，网络差时以最后一次状态为准；倒计时以服务器时间字段为准。
- 人类客户端不提供观战模式；观战使用终端工具。

---

## 8. Agent SDK、示例 Agent 与接入方式

### 8.1 Agent 独立产物

`agents/` 可整体复制到任意机器，不依赖 `server/`：

```
agents/
├─ arena_agent/
│  ├─ __init__.py
│  ├─ protocol.py     # 协议常量、消息校验、方向工具
│  ├─ client.py       # 阻塞式 TCP 客户端 + 回调循环
│  ├─ policy.py       # Policy 基类、上下文、辅助函数
│  └─ pathfinding.py  # BFS 寻路等通用工具
├─ bots/
│  ├─ heuristic.py    # 启发式策略，3 种风格
│  ├─ random_bot.py   # 随机合法动作
│  └─ llm_agent.py    # OpenAI 兼容 LLM 模板
├─ tests/
└─ README.md
```

- 不与服务端共享 Python 包；协议常量各自实现，靠文档和端到端测试保证一致。
- 自定义 Agent 可用任意语言直接实现 TCP 协议，无需 Python。

### 8.2 Python SDK 使用方式

```python
from arena_agent import Policy, run_agent

class MyAgent(Policy):
    def on_start(self, start):
        self.me = start["you"]
        self.rules = start["rules"]

    def decide(self, state):
        # 返回动作字典
        return {"type": "attack", "dir": "n"}

run_agent(
    host="192.168.1.20",
    port=7777,
    name="MyAgent",
    policy=MyAgent(),
    requeue=False,
)
```

SDK 行为：

- 建立 TCP 连接，接收 `welcome`，发送 `join`，自动校验协议版本。
- 收到 `start` → `policy.on_start(start)`。
- 收到 `state` → `policy.decide(state)`；发送带当前 `turn` 的 `action`。
- 收到 `end` → `policy.on_end(end)`；默认退出；`requeue=True` 时短暂等待后重新 `join`。
- 策略抛异常 → 记录日志并发送 `wait`，不崩溃。
- 连续连接失败按 1s/2s/4s 退避重试（上限可配置）。
- 动作被拒绝时打印服务器错误；下一次状态仍会正常处理。
- SDK 提供 `state["you"]`、`state["players"]` 等原始结构，不做隐藏。
- 日志包含自己的玩家 ID、回合、动作和结果摘要，不记录无关连接。

### 8.3 示例 Agent 一：启发式 Bot

`python -m bots.heuristic --host <ip> --port 7777 --name Alpha --strategy balanced`

三种策略：

| strategy | 行为 |
|---|---|
| `aggressive` | 优先接近并攻击最近敌人；HP 低时治疗；能量不足时采集最近节点 |
| `collector` | 优先采集，避免主动交战；被贴身时才反击；保持高能量 |
| `balanced` | 在采集与交战间权衡，护盾/治疗按阈值使用 |

实现要求：

- 从 `start.rules` 读取数值，不硬编码成本/伤害。
- 用 BFS 计算下一步，避开墙、当前占用格；找不到路径时随机合法移动。
- 每次只发一个服务端可接受的动作；本地检查能量、HP、护盾、节点冷却以减少拒绝。
- 加入确定性随机种子（由名字派生），避免同一策略的多个 Bot 完全同步。
- `--quiet` 关闭逐回合输出；默认打印开局、关键时刻、结算。

### 8.4 示例 Agent 二：随机 Bot

`python -m bots.random_bot --host <ip> --port 7777 --name Chaos`

- 从合法动作中等概率选择；用于协议压测和测试。
- 不作为“智能”示例。

### 8.5 示例 Agent 三：LLM Agent 模板

`python -m bots.llm_agent --host <ip> --port 7777 --name Thinker`

环境变量：

| 变量 | 说明 |
|---|---|
| `NEON_ARENA_LLM_BASE_URL` | OpenAI 兼容地址，默认 `http://127.0.0.1:11434/v1` |
| `NEON_ARENA_LLM_MODEL` | 模型名，必填 |
| `NEON_ARENA_LLM_API_KEY` | 可选 Bearer key |
| `NEON_ARENA_LLM_TIMEOUT_MS` | 单次请求超时，默认 10000 |

- 使用标准库 `urllib.request`，不引入 SDK 依赖。
- Prompt 包含：规则摘要、自己状态、敌人状态、节点、最近事件、当前回合；要求只输出一个 JSON 动作。
- 解析失败/超时 → 回退到启发式策略（默认启用），并在下一回合继续。
- `--no-fallback` 时失败则 `wait`。
- 慢模型建议服务端 `--tick-ms 30000`；默认 15000ms 已可覆盖多数中小模型。
- API key 不打印、不写入日志。
- 该模板不锁定特定厂商；任何提供 `/chat/completions` 的服务均可。

### 8.6 远程接入与 NAT

- Agent 主动连接服务器，因此 Agent 所在机器 **不需要公网 IP**，也不需要端口映射；只需能访问服务器 IP:7777。
- 服务器需放行 TCP 7777（Agent）与 8080（HTTP 客户端/API）。
- Windows 防火墙示例（文档提供，不自动执行）：
  `New-NetFirewallRule -DisplayName "Neon Arena" -Direction Inbound -Protocol TCP -LocalPort 7777,8080 -Action Allow`
- 公网部署建议：仅暴露必要端口，使用 VPN/SSH 隧道/反向代理；无 TLS 时不要在不可信网络明文传输。

### 8.7 连接约定汇总

- Agent 使用 **TCP 7777** 直连；人类/自定义客户端使用 **HTTP 8080**。
- Agent 也可以按 HTTP API 接入（协议通用），但推荐 TCP：推送式、低延迟、无需轮询。
- 客户端与 Agent 共用大厅与对局；服务端仅通过 `kind` 区分展示。

---

## 9. 观战、日志与回放

### 9.1 终端观战器

`python -m tools.spectator --host <ip> --port 7777 [--plain] [--no-color] [--once]`

- 以 `spectate` 身份连接，不占玩家席位。
- 接收 `start` / `state` / `end`，用 ASCII 网格 + 状态面板实时渲染。
- 无对局时显示大厅信息，等待下一局。
- 新接入进行中的对局时，服务端补发 `start` 快照。
- `--plain`：不清屏、无 ANSI，适合日志/CI；每回合打印棋盘和事件。
- `--once`：一局结束后退出；默认继续等待下一局。
- 显示：回合、倒计时、节点、玩家字母/颜色、HP/能量/护盾/分数、最近事件。
- 只读，不发送动作。

### 9.2 对局日志

- 每局一个 `logs/match-<YYYYMMDD-HHMMSS>-<id>.jsonl`（默认相对服务端启动目录）。
- 行类型：`start`、`state`（每回合）、`end`。
- 与协议消息结构一致，便于离线分析、训练或回放。
- 不含 IP、token 等敏感信息；玩家名称保留。
- `--no-logs` 可关闭；`--log-dir` 可指定。
- 文件名与 `match_id` 写入 `start`，便于关联。

### 9.3 回放

`python -m tools.spectator --replay logs/xxx.jsonl [--delay 0.2] [--plain]`

- 不连接服务器，按日志重放 `start`/`state`/`end`。
- 与实时观战共用渲染器。
- `--delay 0` 立即输出全部帧，用于快照/测试。
- JSONL 是纯数据，第三方可以自行做 Web 回放。

### 9.4 调试可观测性

- 服务端 `--verbose` 输出每回合动作与事件。
- 错误消息包含回合号和具体原因，Agent 可据此修正。
- `match_id` 与 `seed` 出现在 `start`/`end`/日志中，可复现问题。
- 测试与脚本均以真实端口启动，验证“分进程通信”而非只测内存。

---

## 10. 数据模型与协议约定

### 10.1 核心对象

| 对象 | 字段 |
|---|---|
| RuleSet | HP/能量/护盾上限、初始值、各动作成本与数值、计分、回合计时 |
| Arena | 宽高、墙坐标、节点坐标、出生点 |
| PlayerState | `id, name, kind, pos, hp, shield, energy, score, alive, stats` |
| NodeState | `pos, cooldown, active` |
| MatchStart | `match_id, seed, tick_ms, turn_limit, rules, arena, players, you?` |
| TurnState | `turn, turn_limit, reply_by_ms, players, nodes, events_turn, events, you?` |
| MatchEnd | `match_id, reason, turns, winner, standings, events_turn, events` |
| Event | 见 5.7 的类型化对象 |

### 10.2 坐标与方向

- 坐标 `[x, y]`，原点左上角，x 向右，y 向下。
- 方向：`n` = y-1，`s` = y+1，`w` = x-1，`e` = x+1。
- 所有坐标是数组 `[x, y]`，不用对象，减少 JSON 体积。

### 10.3 版本演进规则

- TCP `protocol` 当前为 1；不兼容变更必须递增。
- HTTP API 版本在 URL 中；`/api/v1` 内只做向后兼容的字段追加。
- 客户端/Agent 必须忽略未知字段，不得因新字段崩溃。
- 服务端启动时打印协议版本；`health` / `welcome` 暴露版本。
- 规则数值以服务端下发为准，客户端不硬编码。

### 10.4 状态一致性

- 服务端是唯一权威；客户端不得自行推进 HP/能量/回合。
- HTTP 视图由当前引擎状态即时生成，`match` 字段在每回合更新。
- TCP 状态是广播快照；`events` 只描述上一回合，不要求客户端持久保存。
- 结算后 `end.standings` 与最后状态一致（以 `end` 为准）。

---

## 11. 目录结构

```
D:\NeonArena\
├─ README.md                     # 总览、三种快速开始、远程部署
├─ .gitignore
├─ server\
│  ├─ arena_server\
│  │  ├─ __init__.py
│  │  ├─ __main__.py
│  │  ├─ config.py
│  │  ├─ engine.py
│  │  ├─ protocol.py
│  │  ├─ lobby.py
│  │  ├─ match.py
│  │  ├─ tcp_gateway.py
│  │  ├─ http_api.py
│  │  ├─ sessions.py
│  │  ├─ logging_utils.py
│  │  └─ server.py
│  ├─ tests\
│  │  ├─ test_engine.py
│  │  ├─ test_map.py
│  │  ├─ test_tcp.py
│  │  └─ test_http_api.py
│  ├─ logs\                        # 默认运行时生成
│  └─ README.md
├─ client\
│  ├─ index.html
│  ├─ style.css
│  ├─ app.js
│  ├─ launcher.py
│  └─ README.md
├─ agents\
│  ├─ arena_agent\
│  │  ├─ __init__.py
│  │  ├─ protocol.py
│  │  ├─ client.py
│  │  ├─ policy.py
│  │  └─ pathfinding.py
│  ├─ bots\
│  │  ├─ __init__.py
│  │  ├─ heuristic.py
│  │  ├─ random_bot.py
│  │  └─ llm_agent.py
│  ├─ tools\
│  │  ├─ __init__.py
│  │  └─ spectator.py
│  ├─ tests\
│  └─ README.md
├─ docs\
│  ├─ PROTOCOL.md                # TCP 协议完整文档
│  ├─ HTTP_API.md                # HTTP API 完整文档
│  ├─ RULES.md                   # 规则、数值、示例
│  ├─ openapi.yaml
│  └─ superpowers\specs\2026-11-23-neon-arena-design.md
├─ tests\
│  └─ test_e2e.py                # 跨进程端到端测试
├─ scripts\
│  ├─ start_server.ps1
│  ├─ demo.ps1
│  └─ play.ps1
```

- `server/logs/` 默认在服务端启动目录下运行时生成（从 `server/` 启动即 `server/logs/`），加入 `.gitignore`。
- `server/tests/` 只依赖服务端；`agents/tests/` 只依赖 Agent SDK。
- 根 `tests/test_e2e.py` 通过子进程启动服务端、Agent 和 HTTP 客户端，验证三块独立产物可以真实通信。
- `scripts/demo.ps1`：启动服务器 + 3 个启发式 Agent + 终端观战器（可选）。
- `scripts/play.ps1`：启动服务器 + 若干 Agent + 客户端 launcher，并打开浏览器，供本地人类玩家体验。

---

## 12. 配置与运行

### 12.1 服务端

```
cd D:\NeonArena\server
python -m arena_server --host 0.0.0.0 --tcp-port 7777 --api-port 8080
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | `0.0.0.0` | TCP 与 HTTP 监听地址 |
| `--tcp-port` | `7777` | Agent TCP 端口 |
| `--api-port` | `8080` | HTTP API 端口 |
| `--tick-ms` | `15000` | 每回合最长等待 |
| `--min-turn-ms` | `250` | 全员提交后的最短展示时间 |
| `--turn-limit` | `80` | 回合上限 |
| `--min-players` | `2` | 开局最少人数（固定 2，仅测试调整） |
| `--max-players` | `4` | 开局最多人数（固定 4，仅测试调整） |
| `--lobby-wait-ms` | `5000` | 达到最少人数后的开赛倒计时 |
| `--max-missed-turns` | `4` | 连续漏操作判负阈值 |
| `--seed` | 随机 | 基础种子；指定后同序号对局可复现 |
| `--log-dir` | `logs` | JSONL 日志目录 |
| `--no-logs` | 关闭 | 不写对局日志 |
| `--cors-origin` | `*` | 允许的客户端源，可逗号分隔 |
| `--max-clients` | `32` | TCP 连接 + HTTP 会话上限 |
| `--verbose` | 关闭 | DEBUG 日志 |
| `--version` | — | 打印版本退出 |

启动成功后打印：

```
Neon Arena 1.0.0
Agent TCP : 0.0.0.0:7777
HTTP API  : http://0.0.0.0:8080/api/v1
LAN hint  : http://192.168.x.x:8080
```

端口被占用、权限不足等启动错误直接退出并给出明确提示。

### 12.2 人类客户端

```
cd D:\NeonArena\client
python launcher.py --server http://192.168.1.20:8080
```

- 默认打开 `http://127.0.0.1:8090/?server=http%3A%2F%2F192.168.1.20%3A8080`。
- 不使用 launcher 时，可直接把 `client/` 静态文件复制给玩家或部署到静态托管，在 UI 里填写服务器地址。
- 客户端 UI 每次连接前调用健康检查，版本不兼容时给出明确提示。

### 12.3 Agent

```
cd D:\NeonArena\agents
python -m bots.heuristic --host 192.168.1.20 --port 7777 --name Alpha --strategy aggressive
python -m bots.heuristic --host 192.168.1.20 --port 7777 --name Beta  --strategy collector
python -m bots.random_bot --host 192.168.1.20 --port 7777 --name Chaos
```

LLM Agent：

```
$env:NEON_ARENA_LLM_MODEL = "your-model"
$env:NEON_ARENA_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
python -m bots.llm_agent --host 192.168.1.20 --port 7777 --name Thinker
```

观战：

```
cd D:\NeonArena\agents
python -m tools.spectator --host 192.168.1.20 --port 7777
```

### 12.4 三人三机部署示例

| 机器 | 运行 |
|---|---|
| 主机 A（服务端） | `cd server; python -m arena_server --host 0.0.0.0` |
| 玩家 B（人类） | `cd client; python launcher.py --server http://A:8080`，浏览器输入名字 |
| Agent C（Bot） | `cd agents; python -m bots.heuristic --host A --port 7777 --name C-Bot` |

- B 与 C 都不需要公网 IP；只需能访问 A 的 8080/7777。
- A 的防火墙放行对应的 TCP 端口。
- 三个进程互不共享文件；所有交互通过 `IP:端口`。

### 12.5 演示脚本

- `scripts/start_server.ps1`：从 `server/` 目录启动服务端，参数透传。
- `scripts/demo.ps1`：启动服务端 + 3 个不同策略的 Bot + 终端观战器；可选 `-OpenClient` 同时启动参考客户端。
- `scripts/play.ps1`：启动服务端 + 2–3 个 Bot + 客户端 launcher 并打开浏览器，供单人体验混合对局。
- 脚本只做进程编排，不包含游戏逻辑；全部端口可通过参数覆盖。

---

## 13. 安全与健壮性

### 13.1 信任模型

- Agent 与人类客户端都不可信；服务端必须校验每个动作、每个字段。
- 游戏没有隐藏信息，因此不存在“客户端窥屏作弊”问题；反作弊不是目标。
- HTTP token 只用于绑定人类会话，不是账号安全机制。
- 服务端不执行来自客户端的代码、不解析表达式、不访问客户端指定的文件路径。

### 13.2 输入安全

- NDJSON 单行上限 64 KiB；HTTP 请求体上限 32 KiB。
- 名称去除控制字符，限制 20 字符；HTML 客户端使用 `textContent`。
- 所有 JSON 输出由标准库序列化；不拼接用户输入生成 JSON。
- 方向/动作白名单校验；未知字段忽略。
- 非法 JSON 不导致服务端崩溃；单连接异常隔离。
- 会话/连接数量上限、频率限制、HTTP 请求超时。

### 13.3 网络与部署

- 默认绑定 `0.0.0.0` 以支持远程接入；文档明确提示公网风险。
- 不提供 TLS；公网部署必须放在 VPN、SSH 隧道或 HTTPS 反向代理之后。
- API CORS 默认 `*` 方便独立客户端；可通过 `--cors-origin` 收紧。
- 无认证的 `join` 意味着任何人都可以加入；这是开放游戏服务器的设计选择。
- 开放端口：TCP 7777 与 TCP 8080；客户端本地端口 8090 不应暴露。
- 服务端 HTTP 端口不提供静态文件，避免目录遍历和客户端代码注入面。

### 13.4 稳定性

- 断线、超时、重复提交、错误回合、非法动作都有明确处理。
- 单局异常以 `aborted` 结束，不影响服务端继续接客。
- 引擎是纯状态机，可单测；网络层只做路由。

---

## 14. 测试与验收

### 14.1 单元测试（server）

- 地图：
  - 相同 seed 生成相同地图；
  - 180° 旋转对称；
  - 出生点/节点不被墙覆盖；
  - 出生点与节点连通；
  - 连续 100 个种子生成不失败。
- 动作校验：
  - 能量不足、墙、越界、非激活节点、满 HP、满护盾；
  - 非法方向、未知动作、缺失字段；
  - 死亡玩家不能行动。
- 移动：
  - 正常移动、撞墙、目标被占、两人同目标都失败；
  - 冲刺被中间格阻挡；
  - 移动后不能穿过其他玩家。
- 战斗：
  - 攻击空位照常扣能量；
  - 护盾吸收、溢出到 HP；
  - 同时互相击杀；
  - 击杀归属与并列规则；
  - 走出攻击范围躲避、走进范围命中。
- 资源与计分：
  - 采集能量/分数/冷却恢复；
  - 能量上限、护盾上限、治疗上限；
  - 伤害/击杀/采集分数累计。
- 结束条件：
  - 最后存活、同时团灭、回合上限、全体判负；
  - 排名与胜负严格符合 3.6。
- 序列化：`state`/`end` 与规则结构符合协议。

### 14.2 传输集成测试（server）

- TCP：
  - 连接后收到 `welcome`；
  - 两个客户端 `join`，大厅广播与倒计时；
  - 开局 `start`、每回合 `state`、`end`；
  - 动作确认、陈旧回合、非法动作、断线判负；
  - 观战者中途接入收到 `start` + 当前 `state`。
- HTTP：
  - health/rules 无需 token；
  - 创建会话、轮询大厅、开局视图；
  - `Authorization` 校验；
  - CORS 预检与响应头；
  - 动作提交、stale/closed、非法动作；
  - `DELETE` 离开与 token 失效；
  - 大厅无轮询清理（测试用短超时）。
- 混合：
  - 一个 TCP Agent + 一个 HTTP 人类会话进入同一局；
  - 双方都能看到对方、提交动作、正常结束。

### 14.3 Agent SDK 测试（agents）

- 消息编解码与协议版本校验。
- `Policy` 回调顺序：start → state* → end。
- 策略异常回退为 wait。
- 寻路避墙/避占用；无路径时合法降级。
- LLM 提示构造、JSON 解析、超时回退（使用本地假 HTTP 服务，不调用真实模型）。

### 14.4 跨进程端到端测试（根 tests/test_e2e.py）

用真实子进程和真实端口：

1. 启动 `server`（临时日志目录、短 tick、低回合上限）。
2. 启动两个 Agent 子进程。
3. 用 HTTP 客户端创建人类会话并轮询/提交动作。
4. 断言：
   - 大厅同时出现 agent 与 human；
   - 收到 start/state，动作被接受；
   - 对局在限定时间内结束；
   - HTTP 会话收到 `mode=ended` 与排名；
   - 服务端退出码正常。
5. 清理所有子进程与临时端口。

该测试是“客户端/服务端分开、IP+端口真实通信”的核心验收依据。

### 14.5 客户端验收

- `client/launcher.py` 能启动并在浏览器打开 UI。
- 静态资源无外链、无第三方依赖。
- 输入服务器地址后可连接；健康检查失败有提示。
- 大厅倒计时、开赛、回合切换、动作提交、等待状态、结算页均正常。
- 键盘与鼠标/触屏方向键都能操作。
- 刷新页面后能凭 token 恢复当前对局。
- 断网恢复后自动重连；服务器重启后提示重新加入。
- 浏览器控制台无报错。
- 桌面与窄屏各截一张图作为验收记录（实现阶段执行）。

### 14.6 手工验收清单

1. 服务端启动，7777/8080 可连通。
2. 三个 Agent 连接、大厅倒计时、开局。
3. 人类客户端从另一进程/机器加入混合对局。
4. 完成一整局，结算正确，日志文件存在。
5. 终端观战器实时显示，回放命令可重放。
6. Agent 断线立即判负，不影响剩余玩家。
7. 非法动作收到明确错误，不扣资源。
8. 同一玩家 4 回合不操作判负。
9. 刷新人类页面恢复对局。
10. 文档中的命令逐条可执行。

### 14.7 验收标准（Definition of Done）

- [ ] 服务端与客户端是两个独立目录、两个独立进程，服务端不返回任何 HTML/JS/CSS。
- [ ] Agent 可通过 `IP:7777` 加入，人类客户端可通过 `IP:8080` 加入，二者可同场。
- [ ] 能完整打完一局并产生获胜者、排名与 JSONL 日志。
- [ ] 参考客户端可连接任意服务器地址，支持大厅、对局、结算、重连。
- [ ] 三个示例 Agent 可运行；LLM 模板有明确配置与回退。
- [ ] 上述单元/集成/端到端测试全部通过。
- [ ] README、协议、HTTP API、OpenAPI、部署与防火墙说明齐全。
- [ ] 零第三方运行依赖；Windows 路径与中文环境可正常使用。
- [ ] 演示脚本可一键复现人类 + 多 Agent 对局。

---

## 15. 实施里程碑

### M1：规则引擎（server）

- 规则数据类、地图生成、玩家状态、动作校验、结算、事件、计分、胜负。
- 单元测试覆盖 14.1。
- 退出条件：纯引擎可在无网络情况下跑完整局，同 seed 结果可复现。

### M2：TCP 网关与单局流程（server）

- lobby、match、TCP NDJSON、计时、连接清理、JSONL 日志。
- 用测试客户端跑通完整对局。
- 退出条件：两个 TCP 客户端可开局并结束；观战者能连接。

### M3：HTTP API（server）

- 会话/token、CORS、health/rules/state/actions/leave、轮询视图、会话清理。
- HTTP 与 TCP 玩家混合测试通过。
- 退出条件：curl/脚本可创建人类会话并完整打完一局。

### M4：Agent SDK、Bots 与观战

- `arena_agent`、启发式/随机/LLM Bot、终端观战器、回放。
- Agent 从独立目录连接真实服务端。
- 退出条件：三 Bot + 一人可完成对局，观战正常。

### M5：独立人类客户端

- 静态 UI、Canvas 渲染、操作面板、轮询/重连、localStorage、launcher。
- 与真实服务端和 Bot 完成浏览器验收。
- 退出条件：14.5 全部通过。

### M6：文档、脚本与最终验收

- README、RULES、PROTOCOL、HTTP_API、OpenAPI、防火墙/部署说明。
- `demo.ps1` / `play.ps1`、根 E2E、截图、最终手工清单。
- 退出条件：14.7 全部勾选。

---

## 16. 风险与取舍

| 取舍 | 原因 | 影响/缓解 |
|---|---|---|
| HTTP 轮询而非 WebSocket | 零依赖、客户端可独立部署、接口简单 | 状态延迟约 350ms；动作提交仍是即时 HTTP 请求，不影响回合决策 |
| 单局而非多局并发 | 观战与大厅简单，适合 4 人竞技 | 超出 4 人排队；后续可扩展分房间 |
| 服务端不托管客户端 | 满足客户端/服务端分离硬约束 | 玩家需本地打开/托管客户端；提供 launcher |
| 无 TLS/账号 | v1 聚焦游戏与 Agent 接入 | 公网部署需自行加 VPN/反向代理；文档明示 |
| 同时决策、同时结算 | 避免先手优势，Agent 对抗更有趣 | 移动碰撞规则略复杂；通过规则文档与事件日志消解歧义 |
| 3 人局位置不完全对称 | 网格四角的天然限制 | 随机出生、统计公平；后续可做三角出生点 |
| 默认 15s 回合上限 | 容忍 LLM/人类思考 | Bot-only 对局因全员提交而仍然快速（250ms/回合） |
| 结束后不自动排队 | 防止无人值守 Bot 无限连赛 | 提供 `--requeue` 显式选项 |
| 大厅 5s 倒计时 | 给人类/远端 Agent 加入窗口 | 可配置；4 人立即开局 |
| CORS 默认 `*` | 参考客户端可独立托管 | 公网用 `--cors-origin` 收紧 |
| 客户端不建模游戏 | 服务端权威，避免不同步 | 网络差时依赖轮询快照；不做本地预测 |

---

## 17. 评审重点（请确认或修改）

1. **分离形态**：服务端只暴露 API、完全不托管 UI；人类客户端是独立静态 Web 客户端（玩家本地启动或托管），Agent 是独立 TCP 客户端。是否符合你对“客户端和服务端分开”的预期？
2. **人类接入**：人类通过 HTTP API 轮询并提交动作，既是参考客户端也是第三方客户端规范。是否接受 HTTP 轮询，而不是 WebSocket？
3. **游戏规则**：15×15、2–4 人、能量经济、同时结算、80 回合；数值是否要调整（更快/更慢、更偏战斗/更偏采集）？
4. **对局节奏**：默认最长 15 秒/回合、全员提交即结算、连续 4 次不操作判负；是否适合人类与 LLM Agent？
5. **单局模式**：单服务器同一时间一局，多余玩家排队，结束后需重新加入；是否接受？
6. **技术栈**：服务端/Agent 纯 Python 标准库，客户端纯原生 Web，无构建、无第三方依赖；是否接受？

评审通过后，下一步是输出详细实施计划（任务拆分、文件级改动、验证步骤），然后再开始编码。




