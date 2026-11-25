(() => {
  "use strict";

  const PROTOCOL = 1;
  const DEFAULT_SERVER = "http://127.0.0.1:8080";
  const MODE_LABELS = {
    classic: "经典混战",
    king: "据点争夺",
    team: "团队 2v2",
    survival: "生存缩圈",
    bounty: "赏金乱斗",
  };
  const MODE_HINTS = {
    classic: "最后存活或最高分获胜",
    king: "留在中心区域，连续占领获得更多分数",
    team: "两队共享积分，队友之间不会受伤",
    survival: "安全区逐步收缩，区外每回合受到风暴伤害",
    bounty: "猎杀 assigned target 可获得双倍伤害分与赏金奖励",
  };
  const PLAYER_COLORS = ["#2de2e6", "#ff4fd8", "#8dff57", "#ffc857"];
  const TEAM_COLORS = { T1: "#2de2e6", T2: "#ff4fd8" };
  const ACTION_NAMES = {
    move: "移动", dash: "冲刺", attack: "攻击", gather: "采集",
    shield: "护盾", heal: "治疗", wait: "等待",
  };
  const DIRECTIONAL = new Set(["move", "dash", "attack"]);
  const DIRS = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] };
  const DIR_NAMES = { n: "北", e: "东", s: "南", w: "西" };
  const KEY_DIRS = {
    arrowup: "n", w: "n", arrowright: "e", d: "e",
    arrowdown: "s", s: "s", arrowleft: "w", a: "w",
  };
  const KEY_ACTIONS = { "1": "move", "2": "dash", "3": "attack", "4": "gather", "5": "shield", "6": "heal", "7": "wait" };
  const REASON_LABELS = {
    last_standing: "最后存活",
    mutual_destruction: "同时团灭",
    score_limit: "达到目标分数",
    turn_limit: "达到回合上限",
    aborted: "服务端中止对局",
    forfeit: "对手离开",
  };

  const state = {
    server: "",
    token: "",
    view: null,
    pollTimer: null,
    pollInFlight: false,
    pollAgain: false,
    backoff: 800,
    selectedAction: null,
    clockOffset: 0,
    submitted: false,
    submitting: false,
    notice: "",
    lastMatchId: null,
    lastTurn: null,
    clockTimer: null,
    boardFrame: null,
  };

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const $ = (id) => document.getElementById(id);
  const screens = Array.from(document.querySelectorAll(".screen"));
  const actionButtons = Array.from(document.querySelectorAll("[data-action]"));
  const directionButtons = Array.from(document.querySelectorAll("[data-dir]"));

  class ApiError extends Error {
    constructor(status, code, message) {
      super(message || code || "request failed");
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.message = this.message || this.code;
    }
  }

  class ApiClient {
    constructor(server, token = "") {
      this.server = server;
      this.token = token;
    }

    async api(path, { method = "GET", body, auth = false } = {}) {
      const headers = { Accept: "application/json" };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (auth) headers.Authorization = `Bearer ${this.token}`;
      let response;
      try {
        response = await fetch(this.server + "/api/v1" + path, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          cache: "no-store",
          credentials: "omit",
          referrerPolicy: "no-referrer",
        });
      } catch (error) {
        throw new ApiError(0, "network_error", "无法连接服务器");
      }
      let data = {};
      try {
        data = await response.json();
      } catch (error) {
        throw new ApiError(response.status, "invalid_response", "服务器返回了无效 JSON");
      }
      if (!response.ok || data.ok === false) {
        const error = data.error || {};
        throw new ApiError(response.status, error.code || "request_failed", error.message || "请求失败");
      }
      return data;
    }

    health() { return this.api("/health"); }
    createSession(name) {
      return this.api("/sessions", { method: "POST", body: { name }, auth: Boolean(this.token) });
    }
    recover() { return this.api("/sessions", { method: "POST", auth: true }); }
    state() { return this.api("/state", { auth: true }); }
    action(turn, action) {
      return this.api("/actions", { method: "POST", auth: true, body: { turn, action } });
    }
    leave() { return this.api("/sessions", { method: "DELETE", auth: true }); }
  }

  function storageGet(key) {
    try { return localStorage.getItem(key) || ""; } catch (error) { return ""; }
  }

  function storageSet(key, value) {
    try { localStorage.setItem(key, value); } catch (error) { /* Storage can be unavailable on file URLs. */ }
  }

  function storageRemove(key) {
    try { localStorage.removeItem(key); } catch (error) { /* Storage can be unavailable on file URLs. */ }
  }

  function tokenKey(server) { return "neon.token." + server; }

  function normalizeServer(raw) {
    let value = String(raw || "").trim();
    if (!value) throw new Error("请输入服务器地址");
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = "http://" + value;
    let url;
    try { url = new URL(value); } catch (error) { throw new Error("服务器地址格式无效"); }
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("服务器地址必须使用 http 或 https");
    if (url.username || url.password) throw new Error("服务器地址不能包含用户名或密码");
    if (url.search || url.hash) throw new Error("服务器地址不能包含查询参数或片段");
    return url.origin + url.pathname.replace(/\/+$/, "");
  }

  function setText(id, value) {
    const element = $(id);
    if (element) element.textContent = String(value ?? "");
  }

  function clear(element) {
    while (element.firstChild) element.removeChild(element.firstChild);
  }

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }

  function setConnection(text, kind = "") {
    const element = $("connection-status");
    element.textContent = text;
    element.className = "connection-status" + (kind ? " " + kind : "");
  }

  function showScreen(id) {
    for (const screen of screens) {
      const active = screen.id === id;
      screen.hidden = !active;
      screen.classList.toggle("active", active);
      screen.setAttribute("aria-hidden", String(!active));
    }
    if (id !== "screen-game") {
      stopBoardLoop();
      stopClock();
    }
  }

  function currentClient() { return new ApiClient(state.server, state.token); }
  function currentMatch() { return state.view && state.view.mode === "match" ? state.view.match : null; }
  function selfPlayer(match = currentMatch()) {
    if (!match || !state.view) return null;
    const youId = match.you || (state.view.you && state.view.you.id);
    return match.players.find((player) => player.id === youId) || null;
  }

  function playerName(players, id) {
    const player = players.find((entry) => entry.id === id);
    return player ? player.name : id || "未知玩家";
  }

  function initial(name) {
    const chars = Array.from(String(name || "?"));
    return (chars[0] || "?").toUpperCase();
  }

  function teamFor(player, modeState) {
    if (!player || !player.team || !modeState || !Array.isArray(modeState.teams)) return null;
    return modeState.teams.find((team) => team.id === player.team) || null;
  }

  function remainingMs(match = currentMatch()) {
    if (!match || !Number.isFinite(match.reply_by_ms)) return 0;
    return Math.max(0, match.reply_by_ms - (Date.now() + state.clockOffset));
  }

  function activeNodeAt(match, player) {
    if (!match || !player) return null;
    return (match.nodes || []).find((node) => node.active && node.pos[0] === player.pos[0] && node.pos[1] === player.pos[1]) || null;
  }

  function availability(match = currentMatch()) {
    const player = selfPlayer(match);
    const rules = (match && match.rules) || {};
    const canAct = Boolean(player && player.alive && !state.submitted && !state.submitting && remainingMs(match) > 0);
    return {
      canAct,
      move: canAct,
      dash: canAct && player.energy >= (rules.dash ? rules.dash.cost : Infinity),
      attack: canAct && player.energy >= (rules.attack ? rules.attack.cost : Infinity),
      gather: canAct && Boolean(activeNodeAt(match, player)),
      shield: canAct && player.energy >= (rules.shield ? rules.shield.cost : Infinity) && player.shield < (rules.shield ? rules.shield.max : 0),
      heal: canAct && player.energy >= (rules.heal ? rules.heal.cost : Infinity) && player.hp < (rules.max_hp || 0),
      wait: canAct,
    };
  }

  function renderActionState() {
    const match = currentMatch();
    if (!match) return;
    const available = availability(match);
    const player = selfPlayer(match);
    for (const button of actionButtons) {
      const action = button.dataset.action;
      button.disabled = !available[action];
      button.classList.toggle("selected", state.selectedAction === action);
      button.setAttribute("aria-pressed", String(state.selectedAction === action));
    }
    const selectedAvailable = state.selectedAction ? available[state.selectedAction] : available.move;
    for (const button of directionButtons) button.disabled = !available.canAct || !selectedAvailable;
    let label = "选择行动";
    if (state.selectedAction) label = ACTION_NAMES[state.selectedAction] + " · 选择方向";
    if (!player || !player.alive) label = "已淘汰 · 观战中";
    if (state.submitted) label = "已提交 · 等待其他玩家";
    setText("selected-action-label", label);
    if (state.notice) {
      setText("game-status", state.notice);
    } else if (state.submitted) {
      setText("game-status", "等待其他玩家");
    } else if (!player || !player.alive) {
      setText("game-status", "你已淘汰，可继续观战");
    } else if (state.selectedAction) {
      setText("game-status", "按 WASD、方向键或点击 D-pad");
    } else {
      setText("game-status", "本回合尚未提交");
    }
  }

  function setNotice(message) {
    state.notice = message || "";
    renderActionState();
  }

  async function submitAction(type, dir) {
    const match = currentMatch();
    if (!match) return;
    const available = availability(match);
    if (!available.canAct || !available[type] || state.submitting) return;
    const action = dir ? { type, dir } : { type };
    state.submitting = true;
    state.notice = "提交中…";
    renderActionState();
    try {
      await currentClient().action(match.turn, action);
      state.submitted = true;
      state.selectedAction = null;
      state.notice = "已提交，等待其他玩家";
      state.backoff = 800;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.code === "unauthorized")) {
        invalidateSession("会话已失效，请重新加入");
        return;
      }
      state.submitted = false;
      state.selectedAction = null;
      if (error instanceof ApiError && (error.status === 409 || error.code === "stale_turn" || error.code === "turn_closed")) {
        state.notice = "回合已更新，正在刷新";
        pollState(true);
      } else if (error instanceof ApiError && error.status === 400) {
        state.notice = actionErrorMessage(error);
      } else if (error instanceof ApiError && error.status === 429) {
        state.notice = "请求过快，请稍后重试";
      } else {
        state.notice = "连接中断，正在确认提交结果…";
        setConnection("重连中", "warning");
        pollState(true);
      }
    } finally {
      state.submitting = false;
      renderActionState();
    }
  }

  function actionErrorMessage(error) {
    const messages = {
      insufficient_energy: "能量不足",
      wall: "目标格不可通行",
      out_of_bounds: "目标超出棋盘",
      no_active_node: "当前没有可采集节点",
      full_hp: "生命已满",
      shield_full: "护盾已满",
      invalid_action: "行动无效",
      not_alive: "你已被淘汰",
    };
    return messages[error.code] || error.message || "行动被拒绝";
  }

  function selectAction(type) {
    const match = currentMatch();
    if (!match) return;
    const available = availability(match);
    if (!available.canAct || !available[type]) return;
    state.notice = "";
    if (DIRECTIONAL.has(type)) {
      state.selectedAction = type;
      renderActionState();
    } else {
      submitAction(type);
    }
  }

  function submitDirection(dir) {
    const type = state.selectedAction && DIRECTIONAL.has(state.selectedAction) ? state.selectedAction : "move";
    submitAction(type, dir);
  }

  function eventDirection(event) {
    if (event.dir) return event.dir;
    if (!Array.isArray(event.from) || !Array.isArray(event.to)) return "";
    const dx = Number(event.to[0]) - Number(event.from[0]);
    const dy = Number(event.to[1]) - Number(event.from[1]);
    if (dx > 0 && dy === 0) return "e";
    if (dx < 0 && dy === 0) return "w";
    if (dy > 0 && dx === 0) return "s";
    if (dy < 0 && dx === 0) return "n";
    return "";
  }

  function formatEvent(event, players, youId) {
    const name = (id) => playerName(players, id);
    const own = (id) => (id === youId ? "你" : name(id));
    const dir = eventDirection(event);
    const direction = dir ? DIR_NAMES[dir] || dir : "";
    switch (event.type) {
      case "move": return `${own(event.player)} ${direction ? "向" + direction : ""}移动到 (${event.to[0]}, ${event.to[1]})`;
      case "dash": return `${own(event.player)} ${direction ? "向" + direction : ""}冲刺至 (${event.to[0]}, ${event.to[1]})`;
      case "blocked": return `${own(event.player)} 的${ACTION_NAMES[event.action] || event.action}被阻挡`;
      case "attack": return `${own(event.player)} ${direction ? "向" + direction : ""}攻击${event.target ? ` (${event.target[0]}, ${event.target[1]})` : "空位"}`;
      case "damage": return `${own(event.player)} 对 ${own(event.target)} 造成 ${event.hp_damage} HP / ${event.shield_damage} 护盾伤害${event.bounty ? "（赏金加成）" : ""}`;
      case "heal": return `${own(event.player)} 恢复 ${event.amount} HP`;
      case "shield": return `${own(event.player)} 获得 ${event.amount} 护盾`;
      case "gather": return `${own(event.player)} 采集 +${event.energy_gain} 能量 / +${event.score_gain} 分`;
      case "death": return event.killer ? `${own(event.killer)} 淘汰了 ${own(event.player)}` : `${own(event.player)} 被淘汰`;
      case "forfeit": return `${own(event.player)} 离开或超时判负`;
      case "hill_score": return `${own(event.player)} 占领据点 +${event.points} 分（连续 ${event.streak} 回合）`;
      case "storm_shrink": return `安全区收缩至 (${event.zone.min[0]},${event.zone.min[1]})–(${event.zone.max[0]},${event.zone.max[1]})`;
      case "storm_damage": return `${own(event.player)} 受到 ${event.amount} 点风暴伤害`;
      case "bounty_complete": return `${own(event.player)} 完成赏金猎杀，获得 ${event.bonus} 分（连杀 ${event.streak}）`;
      case "bounty_retarget": return `${own(event.player)} 的新目标是 ${own(event.target)}`;
      case "friendly_blocked": return `${own(event.player)} 的攻击被队友 ${own(event.target)} 免疫`;
      default: return `${own(event.player || "")} 触发了 ${event.type || "未知事件"}`;
    }
  }

  function meterRow(label, value, maximum, className) {
    const row = makeElement("div", "stat-row");
    row.appendChild(makeElement("span", "", label));
    const meter = makeElement("div", "meter " + className);
    const fill = makeElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, maximum > 0 ? value / maximum * 100 : 0))}%`;
    meter.appendChild(fill);
    row.appendChild(meter);
    row.appendChild(makeElement("strong", "", `${value}${maximum ? " / " + maximum : ""}`));
    return row;
  }

  function renderHud(match) {
    const player = selfPlayer(match);
    if (!player) return;
    const rules = match.rules || {};
    clear($("hud-self"));
    $("hud-self").appendChild(meterRow("HP", player.hp, rules.max_hp || 100, "hp"));
    $("hud-self").appendChild(meterRow("能量", player.energy, rules.max_energy || 100, "energy"));
    $("hud-self").appendChild(meterRow("护盾", player.shield, rules.shield ? rules.shield.max : 40, "shield"));
    $("hud-self").appendChild(meterRow("分数", player.score, 0, "score"));
    setText("self-id", `${player.id} · YOU`);

    clear($("hud-players"));
    const ranked = match.players.slice().sort((a, b) => Number(b.alive) - Number(a.alive) || b.score - a.score || b.hp - a.hp || b.energy - a.energy || a.id.localeCompare(b.id));
    for (const entry of ranked) {
      const row = makeElement("div", "hud-player" + (entry.id === player.id ? " self" : "") + (entry.alive ? "" : " dead"));
      const avatar = makeElement("span", "avatar", initial(entry.name));
      avatar.style.color = PLAYER_COLORS[Math.max(0, Number(entry.id.slice(1)) - 1)] || PLAYER_COLORS[0];
      const info = makeElement("div", "hud-player-name");
      info.appendChild(makeElement("strong", "", entry.name));
      const team = teamFor(entry, match.mode_state);
      const meta = makeElement("div", "hud-player-meta", `${entry.id} · ${entry.kind.toUpperCase()}${team ? " · " + team.name : ""}${entry.hill_streak ? " · 占领 " + entry.hill_streak : ""}${entry.bounty_streak ? " · 赏金 " + entry.bounty_streak : ""}`);
      info.appendChild(meta);
      const meter = makeElement("div", "meter hp");
      const fill = makeElement("span");
      fill.style.width = `${Math.max(0, Math.min(100, entry.hp / (rules.max_hp || 100) * 100))}%`;
      meter.appendChild(fill);
      info.appendChild(meter);
      row.append(avatar, info, makeElement("strong", "hud-score", entry.score));
      $("hud-players").appendChild(row);
    }

    clear($("event-log"));
    const events = Array.isArray(match.events) ? match.events.slice(-8) : [];
    for (const event of events) {
      const line = makeElement("div", "event-line" + (/hill|storm|bounty|friendly/.test(event.type) ? " mode-event" : ""), formatEvent(event, match.players, player.id));
      $("event-log").appendChild(line);
    }
    if (!events.length) $("event-log").appendChild(makeElement("div", "event-line", "等待首个回合结算…"));
  }

  function modeChip(label, value, alert = false) {
    const chip = makeElement("span", "mode-chip" + (alert ? " alert" : ""));
    chip.appendChild(makeElement("strong", "", label + " "));
    chip.appendChild(document.createTextNode(String(value)));
    return chip;
  }

  function zoneText(zone) {
    if (!zone || !zone.min || !zone.max) return "不可用";
    return `(${zone.min[0]},${zone.min[1]})–(${zone.max[0]},${zone.max[1]})`;
  }

  function renderModeHud(match) {
    const hud = $("mode-hud");
    clear(hud);
    const player = selfPlayer(match);
    const modeState = match.mode_state || {};
    switch (match.mode) {
      case "classic":
        hud.appendChild(modeChip("规则", MODE_HINTS.classic));
        break;
      case "king":
        hud.appendChild(modeChip("据点", zoneText(modeState.zone)));
        hud.appendChild(modeChip("目标", `${modeState.target_score || 100} 分`));
        hud.appendChild(modeChip("连续占领", player ? player.hill_streak || 0 : 0));
        break;
      case "survival":
        hud.appendChild(modeChip("安全区", zoneText(modeState.zone)));
        hud.appendChild(modeChip("下次收缩", modeState.next_shrink_turn ? `第 ${modeState.next_shrink_turn} 回合` : "已最终收缩"));
        hud.appendChild(modeChip("风暴伤害", modeState.storm_damage || 0));
        hud.appendChild(modeChip("状态", player && player.in_storm ? "你在风暴中" : "你在安全区", Boolean(player && player.in_storm)));
        break;
      case "team": {
        const ownTeam = teamFor(player, modeState);
        hud.appendChild(modeChip("我的队伍", ownTeam ? ownTeam.name : "未分配"));
        for (const team of modeState.teams || []) hud.appendChild(modeChip(team.name, `${team.score} 分 · ${team.alive} 存活`));
        break;
      }
      case "bounty": {
        const targetId = player ? player.bounty_target || (modeState.targets && modeState.targets[player.id]) : null;
        hud.appendChild(modeChip("赏金目标", targetId ? playerName(match.players, targetId) : "暂无"));
        hud.appendChild(modeChip("赏金连杀", player ? player.bounty_streak || 0 : 0));
        hud.appendChild(modeChip("目标分数", `${modeState.target_score || 150} 分`));
        break;
      }
      default:
        hud.appendChild(modeChip("模式", match.mode || "classic"));
    }
  }

  function renderGame(match) {
    const player = selfPlayer(match);
    const badge = $("mode-badge");
    badge.textContent = (MODE_LABELS[match.mode] || match.mode || "classic").toUpperCase();
    badge.className = "mode-badge mode-" + (match.mode || "classic");
    setText("turn", `${match.turn} / ${match.turn_limit}`);
    setText("game-score", player ? player.score : 0);
    $("board").setAttribute("aria-label", `NEON ARENA ${MODE_LABELS[match.mode] || match.mode}棋盘，第 ${match.turn} 回合`);
    renderModeHud(match);
    renderHud(match);
    renderActionState();
    startClock(match);
    startBoardLoop();
  }

  function renderLobby(lobby) {
    setText("lobby-mode", lobby.mode_label || MODE_LABELS[lobby.mode] || lobby.mode || "等待模式");
    setText("lobby-mode-description", lobby.mode_description || MODE_HINTS[lobby.mode] || "服务器正在选择下一局模式");
    const count = Array.isArray(lobby.players) ? lobby.players.length : 0;
    setText("lobby-count", `${count} / ${lobby.max_players || 4} 人`);
    const seconds = lobby.starts_in_ms === null || lobby.starts_in_ms === undefined ? null : Math.max(0, Math.ceil(lobby.starts_in_ms / 1000));
    setText("lobby-countdown", seconds === null ? `还需 ${Math.max(0, (lobby.min_players || 2) - count)} 人` : `${seconds} 秒后开局`);
    $("lobby-progress").style.setProperty("--progress", seconds === null ? "0" : "1");
    clear($("lobby-players"));
    for (const player of lobby.players || []) {
      const item = makeElement("li");
      item.appendChild(makeElement("strong", "", player.name));
      item.appendChild(makeElement("span", "kind", player.kind === "human" ? "HUMAN" : "AGENT"));
      $("lobby-players").appendChild(item);
    }
    setConnection("已连接", "online");
  }

  function resultRow(values) {
    const row = document.createElement("tr");
    for (const value of values) row.appendChild(makeElement("td", "", value));
    return row;
  }

  function renderResult(result, match) {
    const players = result.standings || [];
    const winner = result.winner;
    clear($("result-winner"));
    setText("result-winner", winner ? `${winner.name} 获胜` : "本局无人获胜");
    if (winner && winner.kind === "team" && Array.isArray(winner.members)) {
      $("result-winner").appendChild(makeElement("div", "result-members", `成员：${winner.members.map((id) => playerName(players, id)).join("、")}`));
    }
    setText("result-reason", REASON_LABELS[result.reason] || result.reason || "对局结束");
    setText("result-status", "");
    setText("result-turns", `${result.turns || 0} 回合 · ${MODE_LABELS[result.mode] || result.mode || "经典混战"}`);

    clear($("result-standings"));
    players.forEach((player, index) => {
      const stats = player.stats || {};
      const team = teamFor(player, result.mode_state);
      $("result-standings").appendChild(resultRow([
        index + 1,
        `${player.name} (${player.id})${team ? " · " + team.name : ""}`,
        player.score,
        player.hp,
        stats.damage_dealt || 0,
        stats.kills || 0,
        stats.gathered || 0,
      ]));
    });

    const teamStandings = Array.isArray(result.team_standings) ? result.team_standings : [];
    $("result-team-panel").hidden = teamStandings.length === 0;
    clear($("result-team-standings"));
    teamStandings.forEach((team, index) => {
      $("result-team-standings").appendChild(resultRow([
        index + 1,
        team.name || team.id,
        team.members.map((id) => playerName(players, id)).join("、"),
        team.score,
        `${team.alive}/${team.members.length}`,
      ]));
    });

    clear($("result-stats"));
    const stats = [
      ["回合", result.turns || 0],
      ["存活", players.filter((player) => player.alive).length],
      ["总伤害", players.reduce((sum, player) => sum + ((player.stats && player.stats.damage_dealt) || 0), 0)],
      ["总击杀", players.reduce((sum, player) => sum + ((player.stats && player.stats.kills) || 0), 0)],
      ["总采集", players.reduce((sum, player) => sum + ((player.stats && player.stats.gathered) || 0), 0)],
      ["地图种子", match && match.seed !== undefined ? match.seed : "—"],
    ];
    for (const [label, value] of stats) {
      const card = makeElement("div", "result-stat");
      card.appendChild(makeElement("span", "", label));
      card.appendChild(makeElement("strong", "", value));
      $("result-stats").appendChild(card);
    }
    setConnection("对局已结束", "online");
  }

  function applyView(view) {
    if (!view || typeof view.mode !== "string") throw new ApiError(0, "invalid_response", "服务器返回了无效状态视图");
    if (view.server && Number.isFinite(view.server.now_ms)) state.clockOffset = view.server.now_ms - Date.now();
    state.view = view;
    state.backoff = 800;
    if (view.mode === "match" && view.match) {
      const match = view.match;
      const newTurn = match.match_id !== state.lastMatchId || match.turn !== state.lastTurn;
      if (newTurn) {
        state.submitted = Boolean(match.submitted);
        state.submitting = false;
        state.selectedAction = null;
        state.notice = "";
        state.lastMatchId = match.match_id;
        state.lastTurn = match.turn;
      } else if (match.submitted) {
        state.submitted = true;
      }
      showScreen("screen-game");
      renderGame(match);
    } else if (view.mode === "lobby" && view.lobby) {
      state.lastMatchId = null;
      state.lastTurn = null;
      state.submitted = false;
      state.selectedAction = null;
      state.notice = "";
      showScreen("screen-lobby");
      renderLobby(view.lobby);
    } else if (view.mode === "ended" && view.result) {
      state.lastMatchId = null;
      state.lastTurn = null;
      state.submitted = false;
      state.selectedAction = null;
      state.notice = "";
      showScreen("screen-result");
      renderResult(view.result, view.match);
    } else {
      throw new ApiError(0, "invalid_response", "未知的状态视图");
    }
  }

  function pollDelay() {
    if (document.hidden) return 1500;
    if (!state.view) return 800;
    if (state.view.mode === "match") return 350;
    if (state.view.mode === "ended") return 1500;
    return 800;
  }

  function schedulePoll(delay) {
    if (state.pollTimer !== null) clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(() => {
      state.pollTimer = null;
      pollState();
    }, Math.max(0, delay));
  }

  async function pollState(force = false) {
    if (!state.token) return;
    if (state.pollInFlight) {
      if (force) state.pollAgain = true;
      return;
    }
    if (state.pollTimer !== null) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
    state.pollInFlight = true;
    let delay = pollDelay();
    try {
      const data = await currentClient().state();
      applyView(data.view);
      state.backoff = 800;
      setConnection("已连接", "online");
      if (state.notice === "重连中…" || state.notice === "请求过快，稍后重试") {
        state.notice = "";
        renderActionState();
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession("会话已失效，请重新加入");
        return;
      }
      if (error instanceof ApiError && error.status === 429) {
        delay = Math.max(1500, state.backoff);
        setNoticeSafe("请求过快，稍后重试");
      } else {
        delay = Math.min(state.backoff, 5000);
        setNoticeSafe("重连中…");
      }
      state.backoff = Math.min(state.backoff * 2, 5000);
      setConnection("重连中", "warning");
    } finally {
      state.pollInFlight = false;
      const immediate = state.pollAgain;
      state.pollAgain = false;
      if (state.token) schedulePoll(immediate ? 0 : delay);
    }
  }

  function setNoticeSafe(message) {
    if (currentMatch()) {
      state.notice = message;
      renderActionState();
    } else if (!state.view) {
      setText("health-status", message);
    }
  }

  function startPolling() {
    if (!state.token) return;
    if (state.pollInFlight) {
      state.pollAgain = true;
      return;
    }
    schedulePoll(0);
  }

  function stopPolling() {
    if (state.pollTimer !== null) clearTimeout(state.pollTimer);
    state.pollTimer = null;
    state.pollAgain = false;
  }

  function invalidateSession(message) {
    if (state.server) storageRemove(tokenKey(state.server));
    state.token = "";
    state.view = null;
    state.submitted = false;
    state.submitting = false;
    state.selectedAction = null;
    state.notice = "";
    state.lastMatchId = null;
    state.lastTurn = null;
    stopPolling();
    stopBoardLoop();
    stopClock();
    showScreen("screen-connect");
    setText("health-status", "未连接");
    setText("connect-error", message || "会话已结束");
    setConnection("未连接", "");
  }

  async function handleConnect(event) {
    event.preventDefault();
    const button = $("connect");
    button.disabled = true;
    setText("connect-error", "");
    setText("health-status", "健康检查中…");
    let server;
    try {
      server = normalizeServer($("server").value);
      if (state.server && state.server !== server) storageRemove(tokenKey(state.server));
      state.server = server;
      storageSet("neon.server", server);
      state.token = storageGet(tokenKey(server));
      const client = new ApiClient(server, state.token);
      const health = await client.health();
      if (health.protocol !== PROTOCOL) throw new ApiError(0, "protocol_mismatch", `协议不兼容：客户端 ${PROTOCOL}，服务器 ${health.protocol}`);
      setText("health-status", `${health.server || "Neon Arena"} ${health.version || ""} · 协议 ${health.protocol} · 健康检查成功`);
      const name = $("name").value.trim();
      let data;
      if (state.token) {
        data = await client.state();
      } else {
        if (!name) throw new ApiError(400, "invalid_name", "请输入玩家名称");
        data = await client.createSession(name);
      }
      state.token = data.token || state.token;
      if (state.token) storageSet(tokenKey(server), state.token);
      applyView(data.view);
      startPolling();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : error.message;
      setText("health-status", state.token ? "重连中…" : "连接失败");
      setText("connect-error", message);
      setConnection(state.token ? "重连中" : "连接失败", state.token ? "warning" : "error");
      if (state.token) startPolling();
    } finally {
      button.disabled = false;
    }
  }

  async function handleLeave() {
    if (!state.token) {
      invalidateSession();
      return;
    }
    const buttons = [$("leave-lobby"), $("leave-result")];
    buttons.forEach((button) => { button.disabled = true; });
    try {
      await currentClient().leave();
      invalidateSession("已离开服务器");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession("会话已失效，请重新加入");
      } else {
        setText("result-status", error.message || "离开失败，请重试");
        setConnection("重连中", "warning");
        startPolling();
      }
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  async function handleAgain() {
    if (!state.token || !state.view || !state.view.you) return;
    $("again").disabled = true;
    setText("result-status", "正在重新排队…");
    try {
      const data = await currentClient().createSession(state.view.you.name);
      state.token = data.token || state.token;
      storageSet(tokenKey(state.server), state.token);
      applyView(data.view);
      startPolling();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession("会话已失效，请重新加入");
        return;
      }
      setText("result-status", error.message || "重新排队失败，请重试");
    } finally {
      $("again").disabled = false;
    }
  }

  function startClock(match) {
    stopClock();
    updateCountdown(match);
    state.clockTimer = setInterval(() => updateCountdown(match), 100);
  }

  function stopClock() {
    if (state.clockTimer !== null) clearInterval(state.clockTimer);
    state.clockTimer = null;
  }

  function updateCountdown(match = currentMatch()) {
    if (!match) return;
    const remaining = remainingMs(match);
    const seconds = remaining / 1000;
    setText("countdown", remaining <= 0 ? "结算中" : `${seconds.toFixed(1)} 秒`);
    const total = Number.isFinite(match.tick_ms) && match.tick_ms > 0 ? match.tick_ms : 1;
    $("countdown-progress").style.setProperty("--progress", String(Math.max(0, Math.min(1, remaining / total))));
    if (remaining <= 0 && !state.submitted && !state.notice) setText("game-status", "结算中…");
    renderActionState();
  }

  function canvasContext() {
    const canvas = $("board");
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const width = Math.round(rect.width * dpr);
    const height = Math.round(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: rect.width, height: rect.height };
  }

  function validZone(zone) {
    return zone && Array.isArray(zone.min) && Array.isArray(zone.max) && zone.min.length >= 2 && zone.max.length >= 2;
  }

  function drawBoard(match, timestamp = performance.now()) {
    const surface = canvasContext();
    if (!surface) return;
    const { ctx, width, height } = surface;
    const arena = match.arena || { width: 15, height: 15, walls: [], nodes: [] };
    const cols = arena.width || 15;
    const rows = arena.height || 15;
    const pad = Math.max(12, Math.min(width, height) * 0.035);
    const cell = Math.min((width - pad * 2) / cols, (height - pad * 2) / rows);
    const boardW = cell * cols;
    const boardH = cell * rows;
    const ox = (width - boardW) / 2;
    const oy = (height - boardH) / 2;
    const center = (pos) => [ox + (pos[0] + 0.5) * cell, oy + (pos[1] + 0.5) * cell];

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#050a12";
    ctx.fillRect(0, 0, width, height);
    const glow = ctx.createRadialGradient(width / 2, height / 2, 0, width / 2, height / 2, width * 0.7);
    glow.addColorStop(0, "rgba(45,226,230,0.055)");
    glow.addColorStop(1, "rgba(45,226,230,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);

    ctx.lineWidth = 1;
    for (let x = 0; x <= cols; x += 1) {
      ctx.strokeStyle = x === 0 || x === cols ? "rgba(45,226,230,0.38)" : "rgba(92,144,171,0.12)";
      ctx.beginPath(); ctx.moveTo(ox + x * cell, oy); ctx.lineTo(ox + x * cell, oy + boardH); ctx.stroke();
    }
    for (let y = 0; y <= rows; y += 1) {
      ctx.strokeStyle = y === 0 || y === rows ? "rgba(45,226,230,0.38)" : "rgba(92,144,171,0.12)";
      ctx.beginPath(); ctx.moveTo(ox, oy + y * cell); ctx.lineTo(ox + boardW, oy + y * cell); ctx.stroke();
    }

    for (const pos of arena.walls || []) {
      const x = ox + pos[0] * cell;
      const y = oy + pos[1] * cell;
      ctx.fillStyle = "#111c2c";
      ctx.fillRect(x + 1, y + 1, cell - 2, cell - 2);
      ctx.strokeStyle = "rgba(45,226,230,0.36)";
      ctx.strokeRect(x + 1.5, y + 1.5, cell - 3, cell - 3);
      ctx.fillStyle = "rgba(255,79,216,0.12)";
      ctx.fillRect(x + cell * 0.2, y + cell * 0.2, cell * 0.6, Math.max(1, cell * 0.05));
    }

    drawModeLayer(ctx, match, ox, oy, boardW, boardH, cell);

    for (const node of match.nodes || []) {
      const [cx, cy] = center(node.pos);
      const radius = cell * 0.25;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(Math.PI / 4);
      if (node.active) {
        ctx.shadowColor = "#2de2e6";
        ctx.shadowBlur = cell * 0.45;
        ctx.fillStyle = "rgba(45,226,230,0.28)";
      } else {
        ctx.shadowBlur = 0;
        ctx.fillStyle = "rgba(255,200,87,0.13)";
      }
      ctx.fillRect(-radius, -radius, radius * 2, radius * 2);
      ctx.strokeStyle = node.active ? "#70f7f8" : "#ffc857";
      ctx.lineWidth = Math.max(1, cell * 0.045);
      ctx.strokeRect(-radius, -radius, radius * 2, radius * 2);
      ctx.restore();
      if (!node.active && node.cooldown > 0) {
        ctx.fillStyle = "#ffe4a8";
        ctx.font = `700 ${Math.max(9, cell * 0.24)}px Segoe UI, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(node.cooldown), cx, cy + 0.5);
      }
    }

    const you = selfPlayer(match);
    const targetId = you && match.mode === "bounty" ? you.bounty_target || (match.mode_state && match.mode_state.targets && match.mode_state.targets[you.id]) : null;
    if (targetId) {
      const target = match.players.find((player) => player.id === targetId && player.alive);
      if (target && you) {
        const [sx, sy] = center(you.pos);
        const [tx, ty] = center(target.pos);
        ctx.save();
        ctx.strokeStyle = "rgba(141,255,87,0.68)";
        ctx.lineWidth = Math.max(1, cell * 0.04);
        ctx.setLineDash([cell * 0.16, cell * 0.14]);
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(tx, ty); ctx.stroke();
        ctx.restore();
      }
    }

    for (const player of match.players) drawPlayer(ctx, player, match, center, cell, timestamp, player.id === targetId);

    ctx.fillStyle = "rgba(139,163,184,0.72)";
    ctx.font = `700 ${Math.max(9, cell * 0.18)}px Segoe UI, sans-serif`;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText((MODE_LABELS[match.mode] || match.mode || "CLASSIC").toUpperCase(), ox + 4, Math.max(3, oy - cell * 0.32));
  }

  function drawModeLayer(ctx, match, ox, oy, boardW, boardH, cell) {
    const zone = match.mode_state && match.mode_state.zone && validZone(match.mode_state.zone)
      ? match.mode_state.zone
      : null;
    if (match.mode === "king" && zone) {
      const x = ox + zone.min[0] * cell;
      const y = oy + zone.min[1] * cell;
      const w = (zone.max[0] - zone.min[0] + 1) * cell;
      const h = (zone.max[1] - zone.min[1] + 1) * cell;
      ctx.save();
      ctx.fillStyle = "rgba(255,200,87,0.10)";
      ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = "rgba(255,200,87,0.82)";
      ctx.lineWidth = Math.max(1.5, cell * 0.06);
      ctx.setLineDash([cell * 0.22, cell * 0.12]);
      ctx.strokeRect(x, y, w, h);
      ctx.setLineDash([]);
      ctx.fillStyle = "#ffe4a8";
      ctx.font = `800 ${Math.max(9, cell * 0.22)}px Segoe UI, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("KING ZONE", x + w / 2, y + h / 2);
      ctx.restore();
    } else if (match.mode === "survival" && zone) {
      const x = ox + zone.min[0] * cell;
      const y = oy + zone.min[1] * cell;
      const w = (zone.max[0] - zone.min[0] + 1) * cell;
      const h = (zone.max[1] - zone.min[1] + 1) * cell;
      ctx.save();
      ctx.fillStyle = "rgba(111,58,190,0.34)";
      ctx.fillRect(ox, oy, boardW, y - oy);
      ctx.fillRect(ox, y + h, boardW, oy + boardH - (y + h));
      ctx.fillRect(ox, y, x - ox, h);
      ctx.fillRect(x + w, y, ox + boardW - (x + w), h);
      ctx.strokeStyle = "rgba(173,143,255,0.94)";
      ctx.lineWidth = Math.max(2, cell * 0.065);
      ctx.shadowColor = "#9b7bff";
      ctx.shadowBlur = cell * 0.35;
      ctx.strokeRect(x, y, w, h);
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#d7ccff";
      ctx.font = `800 ${Math.max(9, cell * 0.2)}px Segoe UI, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("SAFE ZONE", x + w / 2, Math.max(oy + cell * 0.3, y - cell * 0.28));
      ctx.restore();
    } else if (match.mode === "team") {
      ctx.save();
      ctx.lineWidth = Math.max(3, cell * 0.1);
      ctx.strokeStyle = TEAM_COLORS.T1;
      ctx.beginPath();
      ctx.moveTo(ox, oy + boardH * 0.28); ctx.lineTo(ox, oy); ctx.lineTo(ox + boardW * 0.5, oy);
      ctx.moveTo(ox, oy + boardH * 0.5); ctx.lineTo(ox, oy + boardH);
      ctx.stroke();
      ctx.strokeStyle = TEAM_COLORS.T2;
      ctx.beginPath();
      ctx.moveTo(ox + boardW * 0.5, oy); ctx.lineTo(ox + boardW, oy); ctx.lineTo(ox + boardW, oy + boardH * 0.72);
      ctx.moveTo(ox + boardW, oy + boardH * 0.5); ctx.lineTo(ox + boardW, oy + boardH); ctx.lineTo(ox, oy + boardH);
      ctx.stroke();
      ctx.restore();
    }
  }

  function drawPlayer(ctx, player, match, center, cell, timestamp, bountyTarget) {
    const [cx, cy] = center(player.pos);
    const radius = cell * 0.28;
    const color = PLAYER_COLORS[Math.max(0, Number(player.id.slice(1)) - 1)] || PLAYER_COLORS[0];
    const team = teamFor(player, match.mode_state);
    ctx.save();
    ctx.globalAlpha = player.alive ? 1 : 0.32;
    if (player.alive) {
      ctx.shadowColor = color;
      ctx.shadowBlur = cell * 0.32;
    }
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#06101a";
    ctx.font = `900 ${Math.max(9, cell * 0.25)}px Segoe UI, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(initial(player.name), cx, cy + 0.5);

    if (player.shield > 0) {
      ctx.strokeStyle = "#b39aff";
      ctx.lineWidth = Math.max(1.5, cell * 0.055);
      ctx.beginPath(); ctx.arc(cx, cy, radius + cell * 0.09, 0, Math.PI * 2); ctx.stroke();
    }
    if (team) {
      ctx.strokeStyle = TEAM_COLORS[team.id] || "#ffffff";
      ctx.lineWidth = Math.max(1.5, cell * 0.055);
      ctx.setLineDash([cell * 0.09, cell * 0.07]);
      ctx.beginPath(); ctx.arc(cx, cy, radius + cell * 0.16, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
    }
    const maxEnergy = (match.rules && match.rules.max_energy) || 100;
    ctx.strokeStyle = "rgba(45,226,230,0.22)";
    ctx.lineWidth = Math.max(1.5, cell * 0.045);
    ctx.beginPath(); ctx.arc(cx, cy, radius + cell * 0.23, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = "#2de2e6";
    ctx.beginPath(); ctx.arc(cx, cy, radius + cell * 0.23, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0, Math.min(1, player.energy / maxEnergy))); ctx.stroke();

    const you = selfPlayer(match);
    if (you && you.id === player.id && player.alive && !reducedMotion.matches) {
      const pulse = (Math.sin(timestamp / 260) + 1) / 2;
      ctx.strokeStyle = `rgba(255,255,255,${0.25 + pulse * 0.35})`;
      ctx.lineWidth = Math.max(1, cell * 0.03);
      ctx.beginPath(); ctx.arc(cx, cy, radius + cell * (0.3 + pulse * 0.14), 0, Math.PI * 2); ctx.stroke();
    }
    if (bountyTarget && player.alive) {
      const size = radius + cell * 0.28;
      ctx.strokeStyle = "#8dff57";
      ctx.lineWidth = Math.max(2, cell * 0.06);
      for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
        ctx.beginPath();
        ctx.moveTo(cx + dx * size, cy + dy * (size - cell * 0.16));
        ctx.lineTo(cx + dx * size, cy + dy * size);
        ctx.lineTo(cx + dx * (size - cell * 0.16), cy + dy * size);
        ctx.stroke();
      }
    }
    if (!player.alive) {
      ctx.strokeStyle = "#ff627d";
      ctx.lineWidth = Math.max(2, cell * 0.06);
      ctx.beginPath();
      ctx.moveTo(cx - radius * 0.6, cy - radius * 0.6); ctx.lineTo(cx + radius * 0.6, cy + radius * 0.6);
      ctx.moveTo(cx + radius * 0.6, cy - radius * 0.6); ctx.lineTo(cx - radius * 0.6, cy + radius * 0.6);
      ctx.stroke();
    }
    const barW = cell * 0.72;
    const barY = cy + radius + cell * 0.29;
    ctx.fillStyle = "rgba(0,0,0,0.65)";
    ctx.fillRect(cx - barW / 2, barY, barW, Math.max(3, cell * 0.07));
    ctx.fillStyle = player.hp > 35 ? "#8dff57" : "#ff627d";
    ctx.fillRect(cx - barW / 2, barY, barW * Math.max(0, Math.min(1, player.hp / ((match.rules && match.rules.max_hp) || 100))), Math.max(3, cell * 0.07));
    ctx.restore();
  }

  function boardTick(timestamp) {
    const match = currentMatch();
    if (!match) {
      state.boardFrame = null;
      return;
    }
    drawBoard(match, timestamp);
    if (!reducedMotion.matches) state.boardFrame = requestAnimationFrame(boardTick);
    else state.boardFrame = null;
  }

  function startBoardLoop() {
    if (state.boardFrame !== null) return;
    const match = currentMatch();
    if (!match) return;
    drawBoard(match, performance.now());
    if (!reducedMotion.matches) state.boardFrame = requestAnimationFrame(boardTick);
  }

  function stopBoardLoop() {
    if (state.boardFrame !== null) cancelAnimationFrame(state.boardFrame);
    state.boardFrame = null;
  }

  function handleKeydown(event) {
    if (!currentMatch()) return;
    const target = event.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) return;
    if (event.key === "Escape") {
      state.selectedAction = null;
      state.notice = "";
      renderActionState();
      return;
    }
    if (target && target.tagName === "BUTTON" && (event.key === " " || event.key === "Enter")) return;
    const key = event.key.toLowerCase();
    if (KEY_ACTIONS[key]) {
      event.preventDefault();
      selectAction(KEY_ACTIONS[key]);
      return;
    }
    if (key === " ") {
      event.preventDefault();
      submitAction("wait");
      return;
    }
    if (KEY_DIRS[key]) {
      event.preventDefault();
      submitDirection(KEY_DIRS[key]);
    }
  }

  $("connect-form").addEventListener("submit", handleConnect);
  $("connect").addEventListener("click", handleConnect);
  $("connect-form").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.tagName === "INPUT") handleConnect(event);
  });
  $("leave-lobby").addEventListener("click", handleLeave);
  $("leave-result").addEventListener("click", handleLeave);
  $("again").addEventListener("click", handleAgain);
  for (const button of actionButtons) button.addEventListener("click", () => selectAction(button.dataset.action));
  for (const button of directionButtons) {
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      submitDirection(button.dataset.dir);
    });
    button.addEventListener("click", (event) => {
      if (event.detail === 0) submitDirection(button.dataset.dir);
    });
  }
  document.addEventListener("keydown", handleKeydown);
  document.addEventListener("visibilitychange", () => {
    if (state.token) {
      if (document.hidden) schedulePoll(1500);
      else pollState(true);
    }
  });
  window.addEventListener("resize", () => {
    if (currentMatch()) drawBoard(currentMatch(), performance.now());
  });

  function initialize() {
    showScreen("screen-connect");
    let requested = "";
    try { requested = new URLSearchParams(window.location.search).get("server") || ""; } catch (error) { requested = ""; }
    let server = requested || storageGet("neon.server") || DEFAULT_SERVER;
    try {
      server = normalizeServer(server);
      storageSet("neon.server", server);
    } catch (error) {
      server = DEFAULT_SERVER;
      setText("connect-error", error.message);
    }
    state.server = server;
    state.token = storageGet(tokenKey(server));
    $("server").value = server;
    if (state.token) {
      setText("health-status", "正在恢复会话…");
      setConnection("重连中", "warning");
      startPolling();
    }
  }

  initialize();
  window.NeonArena = Object.freeze({ ApiClient, ApiError, MODE_LABELS, PROTOCOL });
})();
