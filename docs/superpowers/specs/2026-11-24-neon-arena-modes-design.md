# NEON ARENA 多模式趣味扩展设计

> 项目：NEON ARENA
> 版本：v1.1-draft
> 日期：2026-11-24
> 状态：设计已确认，待生成实施计划
> 基线：`2026-11-23-neon-arena-design.md` 与 `2026-11-23-neon-arena.md`

## 1. 目标

在经典自由混战之外增加四种可玩模式，让人类与 Agent、Agent 与 Agent、人类与人类都能用不同规则完成对局：

1. 据点争夺（King of the Hill）
2. 2v2 团队战（Team 2v2）
3. 生存缩圈（Survival）
4. 赏金乱斗（Bounty）

服务器默认按固定顺序自动轮换模式，也允许通过 `--mode` 固定一种模式。所有模式支持人类和 Agent 任意混搭，沿用现有七种动作、能量经济、大厅、TCP/HTTP 传输与单活动对局约束。

## 2. 非目标

- 不增加房间、投票、账号、持久化排行榜或多局并发。
- 不新增动作类型，不改变经典模式的移动、攻击、采集、治疗、护盾、冲刺和等待规则。
- 不实现道具、聊天、表情、音效或新的游戏内经济。
- 不升级 TCP 协议版本；只追加可选字段，旧客户端忽略未知字段后仍可玩经典模式。
- 不为每种模式复制游戏引擎或网络层。

## 3. 总体架构

采用共享核心加模式层：

```text
server/arena_server/
  engine.py          共享移动、资源、战斗、死亡、漏操作与基础序列化
  modes.py           五种模式的初始化、队伍/目标、计分、场地、胜负与扩展事件
  server.py          模式轮换、大厅可玩模式选择、开局传参
  match.py           原对局循环，传递模式状态
  http_api.py        HTTP 视图追加 mode/mode_state
```

`Engine` 持有 `GameMode` 实例。模式层不直接做网络 I/O，不修改玩家输入，不拥有独立匹配循环。所有模式效果由服务端在回合结算时计算并写入事件和状态。

客户端与 Agent 只读取服务端下发的 `mode`、`mode_state` 和玩家上的可选 `team`、`bounty_target` 字段，不在本地推导规则结果。

## 4. 模式选择与自动轮换

### 4.1 配置

`ServerConfig` 新增：

- `mode: str = "rotation"`
- 可选值：`rotation`、`classic`、`king`、`team`、`survival`、`bounty`

CLI 新增 `--mode`。默认值为 `rotation`，即扩展版本开箱即玩自动轮换；显式传入 `--mode classic` 可保持原始体验。

### 4.2 轮换顺序

固定顺序：

```text
classic -> king -> team -> survival -> bounty -> classic
```

每开始一局，服务器从轮换游标当前模式开始扫描，选择第一个满足当前排队人数的模式：

- `classic`、`king`、`survival`、`bounty` 的最低人数为 2。
- `team` 的最低人数固定为 4。
- 扫描完一轮仍不可玩时回退到 `classic`。
- 开局后游标移动到被选中模式的下一项。

因此只有 2–3 人时自动跳过团队战，不会卡住大厅；达到 4 人后，团队战会在轮到它时正常开启。固定模式下，大厅使用该模式的最低人数，未达到人数不开始倒计时。

### 4.3 大厅与开局字段

大厅快照追加：

- `mode`：下一局实际可玩的模式 ID。
- `mode_label`：展示名。
- `mode_description`：一句话规则说明。

`start` 与 HTTP 比赛视图追加：

- `mode`：模式 ID。
- `mode_state`：该模式的公开状态，结构见第 10 节。

## 5. 共享规则与结算顺序

所有模式继续使用以下基础规则：

- 15×15 地图，2–4 名存活玩家，80 回合默认上限。
- 每回合一个动作；动作校验、能量扣除、同时移动、护盾/治疗/采集、同时攻击、死亡、能量恢复、节点冷却、漏操作判负均保持不变。
- 未提交有效动作连续 4 回合判负；无效动作不能重置漏操作计数。
- 网络断线、主动离开立即判负；团队模式中只淘汰该成员，队伍仍有成员时比赛继续。

统一结束检查顺序：

1. 仅剩一个存活单位：`last_standing`。
2. 没有任何存活单位：`mutual_destruction`。
3. 模式达到目标分数：`score_limit`。
4. 完成回合上限且仍有两个或以上存活单位：`turn_limit`。

团队模式的“存活单位”是队伍；其他模式是玩家。`score_limit` 是新增结束原因，客户端必须与原有四种原因一起处理。

## 5.1 回合制与 Agent 思考时间

五种模式都不包含实时移动、实时瞄准、持续攻击或反应速度判定。每局严格按以下循环进行：

1. 服务端广播当前回合完整状态与绝对截止时间 `reply_by_ms`。
2. 所有存活玩家在同一个决策窗口内提交动作；窗口内允许用新的合法动作覆盖旧动作。
3. 所有存活玩家提交后，不早于 `min_turn_ms` 结算；否则到达 `tick_ms` 截止时间后统一结算。
4. 服务端按动作同时计算移动、战斗、资源、模式效果与胜负，再广播下一回合。

Agent 的 LLM 思考发生在服务端决策窗口内，不会阻塞其他玩家，也不会在本地推进游戏。截止后到达的动作不会追溯生效：本回合按未提交处理，服务端可能已使用 `wait` 结算；下一回合仍可正常参与。

默认 `tick_ms=15000`。使用 LLM Agent 时，部署者应统一提高服务端决策窗口，例如 `--tick-ms 30000` 或 `--tick-ms 60000`，并让 LLM 单次请求超时小于该窗口。窗口对所有玩家一致，不提供某个 Agent 单独延长或抢先结算的能力，以保持同时决策公平性。

## 6. 经典自由混战（classic）

完整保留基线规则和计分：

- 对 HP 造成伤害，按实际 HP 伤害计分。
- 击杀 +25。
- 采集 +10。
- 最后存活、同时团灭或回合上限时按原有排名决胜。

经典模式不发送新增事件，`mode_state` 为：

```json
{}
```

## 7. 据点争夺（king）

### 7.1 区域与得分

- 争夺区域为中心 3×3：`x` 与 `y` 均属于 `6..8`。
- 每回合完成移动、资源、战斗、死亡、漏操作处理后，对仍存活且位于区域内的每名玩家计分。
- 基础得分 5；连续占领奖励为 `min(previous_streak, 5)`。
- 第一次占领得 5 分，第二次 6 分，第三次 7 分，之后每次 10 分。
- 离开区域或死亡会将该玩家的连续占领次数清零；重新进入从 5 分开始。
- 任一玩家达到 100 分时，以 `score_limit` 结束。

### 7.2 状态与事件

`mode_state`：

```json
{
  "zone": {"min": [6, 6], "max": [8, 8]},
  "target_score": 100,
  "streaks": {"P1": 2, "P2": 0}
}
```

玩家序列化追加 `hill_streak`。

新增事件：

```json
{"type":"hill_score","player":"P1","pos":[7,7],"points":6,"streak":2,"score":21}
```

`points` 是本回合实际得分，`streak` 是结算后的连续占领次数。

## 8. 2v2 团队战（team）

### 8.1 队伍与人数

- 固定 4 人开局。
- 按玩家 ID 分组：`P1/P2` 为 `T1`，`P3/P4` 为 `T2`。
- 队伍展示名固定为 `Team A`、`Team B`；协议使用稳定 ID。
- 队伍成绩为成员个人得分之和。
- 队友之间关闭伤害；攻击队友仍消耗能量，但不产生 HP、护盾、伤害分或击杀分。

### 8.2 胜负与排名

- 一队全部成员死亡时，另一队以 `last_standing` 获胜。
- 双方同时团灭时，以 `mutual_destruction` 结束，按队伍排名第一者获胜。
- 回合上限时，以 `turn_limit` 结束，按队伍排名决胜。
- 队伍排名：存活人数降序、总得分降序、总 HP 降序、总能量降序、队伍 ID 升序。
- `end.standings` 仍保留玩家排名，玩家追加 `team` 字段；`end.team_standings` 提供队伍排名。
- 团队模式的 `winner` 是队伍对象：

```json
{"id":"T1","name":"Team A","kind":"team","members":["P1","P2"]}
```

### 8.3 状态与事件

`mode_state`：

```json
{
  "teams": [
    {"id":"T1","name":"Team A","members":["P1","P2"],"score":30,"alive":2},
    {"id":"T2","name":"Team B","members":["P3","P4"],"score":18,"alive":1}
  ]
}
```

玩家序列化追加 `team`。

新增事件：

```json
{"type":"friendly_blocked","player":"P1","target":"P2"}
```

## 9. 生存缩圈（survival）

### 9.1 安全区收缩

初始安全区为内部区域 `[1,1]..[13,13]`。完成第 `6、12、18、24、30` 回合的常规战斗后，安全区四边各向内收缩 1 格，但不小于中心 3×3：

| 收缩回合 | 安全区域 |
|---:|---|
| 初始 | `[1,1]..[13,13]` |
| 6 | `[2,2]..[12,12]` |
| 12 | `[3,3]..[11,11]` |
| 18 | `[4,4]..[10,10]` |
| 24 | `[5,5]..[9,9]` |
| 30 及以后 | `[6,6]..[8,8]` |

### 9.2 风暴伤害

- 收缩完成后，所有仍存活且不在新安全区内的玩家受到 12 点真实 HP 伤害。
- 真实伤害忽略护盾，不计伤害分，不产生击杀归属。
- 玩家仍可进入或穿过风暴区域，但会在回合结束时持续受伤。
- 风暴致死产生普通 `death` 事件，`killer` 为 `null`。

### 9.3 状态与事件

`mode_state`：

```json
{
  "zone": {"min": [2, 2], "max": [12, 12]},
  "next_shrink_turn": 12,
  "storm_damage": 12
}
```

`next_shrink_turn` 在最后一次收缩后为 `null`。玩家序列化追加 `in_storm`。

新增事件：

```json
{"type":"storm_shrink","zone":{"min":[2,2],"max":[12,12]},"next_shrink_turn":12}
{"type":"storm_damage","player":"P1","amount":12,"hp":88}
```

## 10. 赏金乱斗（bounty）

### 10.1 目标分配

- 开局按玩家 ID 循环分配：`P1→P2`、`P2→P3`、`P3→P4`、`P4→P1`；人数不足时循环到下一名玩家。
- 每名玩家同一时刻只有一个目标，目标对所有人可见。
- 每次有人死亡后，所有仍存活玩家重新分配：按 ID 循环找到下一名存活且不是自己的玩家。

### 10.2 得分与连杀

- 对当前目标造成 HP 伤害时，得分翻倍；实际伤害与 `damage_dealt` 不变。
- 击杀当前目标：基础击杀 25 分、赏金奖励 25 分，再加连杀奖励 `min(previous_streak, 4) × 5`。
- 第一次赏金击杀总奖励 50，第二次 55，第三次 60，第四次及以后 65。
- 击杀非目标只有基础 25 分，不增加连杀。
- 任一玩家达到 150 分时，以 `score_limit` 结束。

### 10.3 状态与事件

`mode_state`：

```json
{
  "target_score": 150,
  "targets": {"P1":"P2","P2":"P3","P3":"P4","P4":"P1"}
}
```

玩家序列化追加 `bounty_target`、`bounty_streak`。

`damage` 事件在命中赏金目标时追加 `"bounty": true`。

新增事件：

```json
{"type":"bounty_complete","player":"P1","target":"P2","bonus":50,"streak":1}
{"type":"bounty_retarget","player":"P1","target":"P3"}
```

`bonus` 是本次赏金击杀获得的总击杀奖励，包含基础击杀分、赏金奖励与连杀奖励。

## 11. 协议增量

协议版本保持 `1`。所有新增字段均为追加字段：

- `start`：`mode`、`mode_state`。
- `state`：`mode`、`mode_state`。
- 玩家对象：按模式出现 `team`、`hill_streak`、`in_storm`、`bounty_target`、`bounty_streak`。
- `end`：`mode`、`mode_state`；团队模式增加 `team_standings`，`winner.kind` 可能为 `team`。
- `end.reason` 增加 `score_limit`。
- 大厅：`mode`、`mode_label`、`mode_description`。

动作消息和错误码保持不变。旧 Agent 可以继续发送合法动作，但不会主动追求新目标；更新后的示例 Bot 会利用模式状态。

HTTP `view.match` 与 TCP `start/state` 使用同一组模式字段；大厅 `view.lobby` 追加下一局模式信息。

## 12. Bot 与客户端行为

### 12.1 Agent Bot

- 随机 Bot 保持原有合法动作随机策略。
- 启发式 Bot 从 `start.mode` 和 `mode_state` 读取规则：
  - `king`：优先进入或留在中心区域。
  - `survival`：处于风暴时优先寻路到最近安全格。
  - `team`：只选择敌方玩家作为攻击目标。
  - `bounty`：优先接近自己的赏金目标。
- LLM Agent 的提示词加入模式说明和模式状态；解析失败仍回退到模式感知的启发式策略。

### 12.2 Web 客户端

- 大厅显示下一局模式名称与规则摘要。
- 对局顶部显示模式徽章。
- `king`：高亮中心区域并显示连续占领次数。
- `team`：玩家条与棋盘标记队伍，结算展示队伍排名。
- `survival`：绘制风暴遮罩、安全区边界和下次收缩回合。
- `bounty`：高亮自己的目标并显示连杀。
- 结算页识别 `winner.kind == "team"` 和 `reason == "score_limit"`。
- 不新增操作按钮，继续使用现有动作面板与键盘控制。

## 13. 基线城市修正

在模式层接入前修复 Task 3 审核发现的问题：

1. 回合中途 `forfeit()` 不得把上一回合结算事件与当前判负事件混合；当前事件列表只包含本次判负事件。
2. `Engine.resolve()` 收到格式无效或资源不足而无法成立的动作时，按未提交处理，不得重置漏操作计数。
3. 结束检查按第 5 节顺序实现；团队模式由模式层换算存活单位数。

修正必须增加回归测试，且保持现有 28 项服务器测试通过。

## 14. 测试与验收

### 14.1 单元测试

- 轮换：2 人跳过团队战，4 人可选择团队战，固定模式不轮换。
- 据点：基础分、连续奖励、离开清零、100 分结束。
- 团队：固定分队、友伤关闭且耗能、队伍共享分、整队淘汰、团队排名与获胜对象。
- 缩圈：6 回合收缩表、真实伤害忽略护盾、风暴致死无击杀分、最终 3×3。
- 赏金：循环初始目标、目标伤害双倍分、猎杀奖励与连杀、死亡后重新分配、150 分结束。
- 通用：经典模式行为不变，所有模式保持动作校验、漏操作判负和事件序列化。

### 14.2 集成与端到端

- 至少一个 TCP Agent 与 HTTP 人类在非经典模式完成真实对局。
- 4 个真实参与者完成团队战并产生队伍结算。
- 自动轮换在人数不足时不停滞，大厅能看到下一局模式。
- HTTP 根路径和未知路径仍只返回 JSON 404。
- Agent、观战与 JSONL 回放能识别新增模式事件和 `score_limit`。

### 14.3 浏览器验收

- 大厅显示模式，开局显示对应模式 HUD。
- 据点区域、团队标识、风暴遮罩、赏金目标至少各完成一次真实渲染。
- 鼠标与键盘提交动作、刷新恢复、断线重连、结算与再来一局保持可用。
- 控制台无报错，无外部运行时依赖。

### 14.4 完成标准

- `server`、`agents`、根 E2E 测试全部通过。
- 五种模式均有自动化测试和真实对局路径。
- 人类与 Agent、Agent 与 Agent、人类与人类均可完成不同模式对局。
- README、规则、TCP 协议、HTTP API、OpenAPI 和脚本说明与实现一致。
- 经典模式保持向后兼容，协议版本仍为 1。

## 15. 文件影响范围

预计修改或新增：

- `server/arena_server/modes.py`
- `server/arena_server/engine.py`
- `server/arena_server/config.py`
- `server/arena_server/server.py`
- `server/arena_server/lobby.py`
- `server/arena_server/http_api.py`
- `server/tests/test_modes.py`
- `server/tests/test_rotation.py`
- 现有传输集成测试
- `agents/arena_agent`、`agents/bots`、`agents/tools`
- `client/index.html`、`client/style.css`、`client/app.js`
- `tests/test_e2e.py`
- `scripts/*.ps1`
- `docs/RULES.md`、`docs/PROTOCOL.md`、`docs/HTTP_API.md`、`docs/openapi.yaml`
- 根目录与各组件 README
