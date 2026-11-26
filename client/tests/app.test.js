"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { createHarness, flush, lobbyView, matchView } = require("./client_harness.js");

const SERVER = "http://arena.test";
const OTHER_SERVER = "http://other.test";
const TOKEN_KEY = `neon.token.${SERVER}`;
const OTHER_TOKEN_KEY = `neon.token.${OTHER_SERVER}`;

function activeScreen(harness) {
  return harness.document.querySelectorAll(".screen").find((screen) => screen.classList.contains("active"));
}

function progress(harness, id) {
  return Number(harness.elements.get(id).style.getPropertyValue("--progress"));
}

async function openMatch(harness) {
  harness.timers.runNextTimeout();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view: matchView({ turn: 1 }) });
  await flush();
}

function endedView() {
  return {
    mode: "ended",
    server: { now_ms: Date.now() },
    you: { id: "P1", name: "You" },
    result: {
      winner: null,
      reason: "score_limit",
      turns: 5,
      mode: "classic",
      standings: [],
    },
  };
}

async function openResult(harness) {
  harness.timers.runNextTimeout();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view: endedView() });
  await flush();
}

async function startNextPoll(harness) {
  assert.equal(harness.timers.runNextTimeout(), true, "a poll should be scheduled");
  return harness.request("GET", "/api/v1/state");
}

test("duplicate connect submissions start only one health check", async () => {
  const harness = createHarness();
  harness.elements.get("server").value = SERVER;
  harness.elements.get("name").value = "You";

  harness.elements.get("connect-form").dispatch("submit");
  harness.elements.get("connect-form").dispatch("submit");

  assert.equal(harness.requests.filter((entry) => entry.url === `${SERVER}/api/v1/health`).length, 1);
});

test("switching servers preserves both per-server tokens", async () => {
  const harness = createHarness({
    storage: {
      "neon.server": SERVER,
      [TOKEN_KEY]: "arena-token",
      [OTHER_TOKEN_KEY]: "other-token",
    },
  });
  harness.timers.runNextTimeout();
  harness.elements.get("server").value = OTHER_SERVER;

  harness.elements.get("connect-form").dispatch("submit");

  assert.equal(harness.localStorage.getItem(TOKEN_KEY), "arena-token");
  assert.equal(harness.localStorage.getItem(OTHER_TOKEN_KEY), "other-token");
});

test("a late old-server 401 cannot clear the new server session", async () => {
  const harness = createHarness({
    storage: {
      "neon.server": SERVER,
      [TOKEN_KEY]: "arena-token",
      [OTHER_TOKEN_KEY]: "other-token",
    },
  });
  harness.timers.runNextTimeout();
  const oldPoll = harness.request("GET", "/api/v1/state");
  harness.elements.get("server").value = OTHER_SERVER;
  harness.elements.get("connect-form").dispatch("submit");

  harness.request("GET", "/api/v1/health").resolve({ ok: true, protocol: 1, server: "Other", version: "1" });
  await flush();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view: lobbyView({ name: "Other Lobby" }) });
  await flush();
  assert.equal(activeScreen(harness).id, "screen-lobby");

  oldPoll.resolve({ ok: false, status: 401, error: { code: "unauthorized", message: "expired" } }, 401);
  await flush();

  assert.equal(activeScreen(harness).id, "screen-lobby");
  assert.equal(harness.elements.get("lobby-mode").textContent, "Other Lobby");
  assert.equal(harness.localStorage.getItem(OTHER_TOKEN_KEY), "other-token");
});

test("a late old-server state cannot overwrite the new server view", async () => {
  const harness = createHarness({
    storage: {
      "neon.server": SERVER,
      [TOKEN_KEY]: "arena-token",
      [OTHER_TOKEN_KEY]: "other-token",
    },
  });
  harness.timers.runNextTimeout();
  const oldPoll = harness.request("GET", "/api/v1/state");
  harness.elements.get("server").value = OTHER_SERVER;
  harness.elements.get("connect-form").dispatch("submit");

  harness.request("GET", "/api/v1/health").resolve({ ok: true, protocol: 1, server: "Other", version: "1" });
  await flush();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view: lobbyView({ name: "Other Lobby" }) });
  await flush();

  oldPoll.resolve({ ok: true, view: lobbyView({ name: "Old Lobby" }) });
  await flush();

  assert.equal(activeScreen(harness).id, "screen-lobby");
  assert.equal(harness.elements.get("lobby-mode").textContent, "Other Lobby");
});

test("a successful action from the previous turn cannot submit the new turn", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  await openMatch(harness);
  const poll = await startNextPoll(harness);

  harness.elements.get("action-wait").click();
  const action = harness.request("POST", "/api/v1/actions");
  assert.ok(action, "the action request should be in flight");

  poll.resolve({ ok: true, view: matchView({ turn: 2 }) });
  await flush();
  action.resolve({ ok: true });
  await flush();

  assert.equal(activeScreen(harness).id, "screen-game");
  assert.equal(harness.elements.get("turn").textContent, "2 / 5");
  assert.equal(harness.elements.get("action-wait").disabled, false);
});

test("a stale action 401 cannot invalidate a newer turn", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  await openMatch(harness);
  const poll = await startNextPoll(harness);

  harness.elements.get("action-wait").click();
  const action = harness.request("POST", "/api/v1/actions");
  poll.resolve({ ok: true, view: matchView({ turn: 2 }) });
  await flush();
  action.resolve({ ok: false, status: 401, error: { code: "unauthorized", message: "expired" } }, 401);
  await flush();

  assert.equal(activeScreen(harness).id, "screen-game");
  assert.equal(harness.elements.get("turn").textContent, "2 / 5");
  assert.equal(harness.localStorage.getItem(TOKEN_KEY), "arena-token");
});

test("a poll started before Leave cannot restore the lobby afterward", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  harness.timers.runNextTimeout();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view: lobbyView({ name: "Before Leave" }) });
  await flush();
  const oldPoll = await startNextPoll(harness);

  harness.elements.get("leave-lobby").click();
  const leave = harness.request("DELETE", "/api/v1/sessions");
  assert.ok(leave, "the leave request should be in flight");
  leave.resolve({ ok: true });
  await flush();
  assert.equal(activeScreen(harness).id, "screen-connect");

  oldPoll.resolve({ ok: true, view: lobbyView({ name: "Late Lobby" }) });
  await flush();

  assert.equal(activeScreen(harness).id, "screen-connect");
  assert.equal(harness.localStorage.getItem(TOKEN_KEY), null);
  assert.equal(harness.timers.pendingTimeouts, 0);
});

test("Leave ignores Again while leaving and clears transition state on success", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  await openResult(harness);

  harness.elements.get("leave-result").click();
  const leave = harness.request("DELETE", "/api/v1/sessions");
  assert.ok(leave, "the leave request should be in flight");
  harness.elements.get("again").dispatch("click");

  assert.equal(
    harness.requests.filter((entry) => entry.options.method === "POST" && entry.url === `${SERVER}/api/v1/sessions`).length,
    0,
    "Again must not start while Leave is in flight",
  );

  leave.resolve({ ok: true });
  await flush();

  assert.equal(activeScreen(harness).id, "screen-connect");
  assert.equal(harness.localStorage.getItem(TOKEN_KEY), null);
  assert.equal(harness.elements.get("again").disabled, false);
  assert.equal(harness.elements.get("leave-lobby").disabled, false);
  assert.equal(harness.elements.get("leave-result").disabled, false);
  assert.equal(harness.timers.pendingTimeouts, 0, "Leave must not restart polling without a token");
});

test("Leave ignores Again while leaving and recovers polling after failure", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  await openResult(harness);

  harness.elements.get("leave-result").click();
  const leave = harness.request("DELETE", "/api/v1/sessions");
  assert.ok(leave, "the leave request should be in flight");
  harness.elements.get("again").dispatch("click");

  assert.equal(
    harness.requests.filter((entry) => entry.options.method === "POST" && entry.url === `${SERVER}/api/v1/sessions`).length,
    0,
    "Again must not start while Leave is in flight",
  );

  leave.resolve({ ok: false, status: 500, error: { code: "leave_failed", message: "leave failed" } }, 500);
  await flush();

  assert.equal(activeScreen(harness).id, "screen-result");
  assert.equal(harness.localStorage.getItem(TOKEN_KEY), "arena-token");
  assert.equal(harness.elements.get("again").disabled, false);
  assert.equal(harness.elements.get("leave-lobby").disabled, false);
  assert.equal(harness.elements.get("leave-result").disabled, false);

  const poll = await startNextPoll(harness);
  poll.resolve({ ok: true, view: endedView() });
  await flush();
  assert.equal(activeScreen(harness).id, "screen-result");

  harness.elements.get("again").click();
  assert.ok(harness.request("POST", "/api/v1/sessions"), "Again should not remain stuck after Leave fails");
});

test("Again ignores Leave while requeueing and resumes polling on success", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  await openResult(harness);

  harness.elements.get("again").click();
  const again = harness.request("POST", "/api/v1/sessions");
  assert.ok(again, "the again request should be in flight");
  harness.elements.get("leave-result").dispatch("click");

  assert.equal(
    harness.requests.filter((entry) => entry.options.method === "DELETE" && entry.url === `${SERVER}/api/v1/sessions`).length,
    0,
    "Leave must not start while Again is in flight",
  );

  again.resolve({ ok: true, token: "new-arena-token", view: lobbyView({ name: "New Lobby" }) });
  await flush();

  assert.equal(activeScreen(harness).id, "screen-lobby");
  assert.equal(harness.localStorage.getItem(TOKEN_KEY), "new-arena-token");
  assert.equal(harness.elements.get("again").disabled, false);
  assert.equal(harness.elements.get("leave-lobby").disabled, false);
  assert.equal(harness.elements.get("leave-result").disabled, false);
  await startNextPoll(harness);
});

test("Again ignores Leave while requeueing and recovers polling after failure", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  await openResult(harness);

  harness.elements.get("again").click();
  const again = harness.request("POST", "/api/v1/sessions");
  assert.ok(again, "the again request should be in flight");
  harness.elements.get("leave-result").dispatch("click");

  assert.equal(
    harness.requests.filter((entry) => entry.options.method === "DELETE" && entry.url === `${SERVER}/api/v1/sessions`).length,
    0,
    "Leave must not start while Again is in flight",
  );

  again.resolve({ ok: false, status: 500, error: { code: "again_failed", message: "again failed" } }, 500);
  await flush();

  assert.equal(activeScreen(harness).id, "screen-result");
  assert.equal(harness.localStorage.getItem(TOKEN_KEY), "arena-token");
  assert.equal(harness.elements.get("again").disabled, false);
  assert.equal(harness.elements.get("leave-lobby").disabled, false);
  assert.equal(harness.elements.get("leave-result").disabled, false);

  const poll = await startNextPoll(harness);
  poll.resolve({ ok: true, view: endedView() });
  await flush();
  assert.equal(activeScreen(harness).id, "screen-result");

  harness.elements.get("leave-result").click();
  assert.ok(harness.request("DELETE", "/api/v1/sessions"), "Leave should not remain stuck after Again fails");
});

test("lobby countdown progress decreases as starts_in_ms decreases", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  harness.timers.runNextTimeout();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view: lobbyView({ startsInMs: 5000 }) });
  await flush();
  assert.equal(progress(harness, "lobby-progress"), 1);

  const poll = await startNextPoll(harness);
  poll.resolve({ ok: true, view: lobbyView({ startsInMs: 2500 }) });
  await flush();

  assert.equal(progress(harness, "lobby-progress"), 0.5);
  assert.equal(harness.elements.get("lobby-countdown").textContent, "3 秒后开局");
});

test("survival lobby fallback states the exact shrink schedule and true HP damage", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  const view = lobbyView({ name: "生存缩圈" });
  view.lobby.mode = "survival";
  view.lobby.mode_description = "";
  harness.timers.runNextTimeout();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view });
  await flush();

  assert.equal(
    harness.elements.get("lobby-mode-description").textContent,
    "安全区逐步收缩，第 6/12/18/24/30 回合收缩后，区外玩家受到 12 点真实 HP 伤害",
  );
});

test("survival HUD and events describe shrink-only true HP damage", async () => {
  const harness = createHarness({ storage: { "neon.server": SERVER, [TOKEN_KEY]: "arena-token" } });
  const view = matchView({ turn: 12 });
  view.match.mode = "survival";
  view.match.mode_state = {
    zone: { min: [2, 2], max: [12, 12] },
    next_shrink_turn: 18,
    storm_damage: 12,
  };
  view.match.players[0].in_storm = true;
  view.match.events = [
    { type: "storm_shrink", zone: view.match.mode_state.zone, next_shrink_turn: 18 },
    { type: "storm_damage", player: "P1", amount: 12, hp: 88 },
  ];
  harness.timers.runNextTimeout();
  harness.request("GET", "/api/v1/state").resolve({ ok: true, view });
  await flush();

  const chips = harness.elements.get("mode-hud").children.map((chip) => chip.textContent);
  assert.ok(chips.includes("收缩时风暴伤害 12 真实 HP"));
  assert.ok(!chips.some((chip) => chip.includes("每回合")));
  assert.equal(
    harness.elements.get("event-log").children[1].textContent,
    "你 因位于安全区外受到 12 点真实 HP 风暴伤害",
  );
});
