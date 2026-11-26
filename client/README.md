# NEON ARENA 独立 Web 客户端

纯 HTML / CSS / JavaScript 的人类客户端，无构建步骤、框架、CDN、外部字体或图片。服务端仍是唯一权威；本客户端只渲染 HTTP `view`、提交动作并管理浏览器会话。

## 快速开始

需要 Python 3.10+ 和现代浏览器；运行行为回归测试另需 Node.js 18+，客户端运行时不需要 Node.js。

```powershell
cd D:\NeonArena\client
python launcher.py --server http://127.0.0.1:8080
```

默认启动地址为 `http://127.0.0.1:8090/`。`--server` 会以 URL 编码写入打开地址的 `?server=` 查询参数，不会把游戏令牌放入 URL。

```powershell
python launcher.py --host 127.0.0.1 --port 8090 --server http://127.0.0.1:8080 --no-open
```

然后手动访问终端打印的地址。服务端应单独启动，例如：

```powershell
cd D:\NeonArena\server
python -m arena_server --host 127.0.0.1 --mode king --tick-ms 15000 --turn-limit 5 --no-logs
```

也可以把 `index.html`、`style.css`、`app.js` 部署到任意静态站点。直接使用 `file://` 打开时，部分浏览器会限制 `fetch` 或 `localStorage`，推荐使用 launcher。

## 功能

- 连接页：可配置服务器地址、玩家名称、健康检查与协议校验。
- 大厅页：玩家列表、human/agent 标识、人数、倒计时、下一局模式与规则摘要。
- 对局页：DPR 自适应 Canvas、回合倒计时、HP/能量/护盾/分数、排名、最近 8 条事件。
- 结算页：胜者、结束原因、玩家排名、伤害/击杀/采集统计、队伍排名、再来一局与离开。
- 操作：鼠标/触屏按钮、WASD、方向键、数字键 `1..7`、`Space` 等待、`Esc` 取消方向模式。
- 恢复：按服务器地址隔离 token，刷新后通过 `GET /state` 恢复大厅、对局或结算。
- 重连：单次 `setTimeout` 轮询链，大厅 800ms、比赛 350ms、结算 1500ms、隐藏页面 1500ms；网络错误指数退避至 5 秒。
- 提交：成功后锁定本回合输入；400 解锁重试，409 立即刷新，401 清除 token 并提示重新加入。

## 五种模式视觉

| 模式 | 客户端展示 |
| --- | --- |
| `classic` | 标准霓虹棋盘、玩家颜色、HP/能量/护盾与节点冷却 |
| `king` | 中心 `mode_state.zone` 覆盖层、目标分数与 `hill_streak` |
| `team` | 队伍配色边框与玩家环、队伍 HUD、`team_standings` 和队伍胜者成员 |
| `survival` | 安全区外风暴遮罩、安全区边界、下次收缩回合与 `in_storm` |
| `bounty` | 自己至目标的虚线标记、目标准星、`bounty_target` / `bounty_streak` |

结算会识别 `reason == "score_limit"`（显示“达到目标分数”）和 `winner.kind == "team"`。

## HTTP 契约与本地存储

`ApiClient` 提供 `health()`、`createSession(name)`、`recover()`、`state()`、`action(turn, action)`、`leave()`。所有 HTTP API 请求使用 `/api/v1`；鉴权仅通过 `Authorization: Bearer <token>` 请求头。

浏览器存储键：

- `neon.server`：最近使用的服务器地址。
- `neon.token.<server>`：与该服务器地址绑定的会话令牌。

切换服务器地址时按 `neon.token.<server>` 隔离读取，不会把旧服务器的 token 发送到新地址。网络错误不会删除 token；只有服务端返回 401 或主动离开成功时才清除当前服务器的 token。

## 安全边界

- launcher 只使用 Python 标准库，默认仅监听 `127.0.0.1`；端口被占用时会明确报错退出。
- 只允许 GET / HEAD，只服务 `/`（`index.html`）、`/style.css`、`/app.js` 三个公开路由，不提供 `/index.html` 或目录列表。
- 路径解码后只接受上述精确路由；绝对 URI、编码斜杠、`.`、`..`、反斜杠绕过及非白名单文件均被拒绝，并验证解析后的路径仍位于客户端目录内。
- launcher 不代理 `/api`，不读取服务端目录，不修改任何游戏状态。
- 动态玩家名称、错误、事件、排名和模式文本全部通过 `textContent` 创建；代码不使用 `innerHTML`。
- 无外部运行时依赖；静态响应启用 `nosniff`、`no-referrer` 和限制脚本来源的 CSP。

公网部署时需自行配置 HTTPS / VPN，并正确设置服务端 CORS。令牌是本地会话凭据，不应分享给他人。

## 测试

```powershell
cd D:\NeonArena\client
python -m unittest discover -s tests -v
node --test
```

静态测试覆盖必需文件、零外链、`textContent` 约束、四个页面与可访问性、Canvas/操作/轮询契约、五种模式渲染钩子、响应式与减少动画样式，以及 launcher 的标准库和只读边界。运行时测试通过子进程启动 launcher，验证三个公开路由、HEAD、私密/遍历/API 路径拒绝、POST 不支持、端口占用错误退出，以及 Windows 兼容的进程终止与等待清理。

Node 内置测试运行 `tests/app.test.js`，通过轻量 DOM 与可延迟的 fetch 执行真实 `app.js`，覆盖重复连接、服务器切换及 token 保留、旧会话响应/401、跨回合动作响应、Leave/Again 互斥与轮询竞态，以及大厅倒计时进度递减。
