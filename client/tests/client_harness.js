"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CLIENT = path.resolve(__dirname, "..");

class FakeClassList {
  constructor(element) {
    this.element = element;
  }

  values() {
    return new Set(this.element.className.split(/\s+/).filter(Boolean));
  }

  contains(name) {
    return this.values().has(name);
  }

  add(name) {
    if (!this.contains(name)) this.element.className = [...this.values(), name].join(" ");
  }

  remove(name) {
    this.element.className = [...this.values()].filter((value) => value !== name).join(" ");
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.contains(name) : Boolean(force);
    if (enabled) this.add(name);
    else this.remove(name);
    return enabled;
  }
}

class FakeTextNode {
  constructor(text) {
    this.textContent = String(text);
    this.parentNode = null;
  }
}

class FakeElement {
  constructor(tagName, attributes = {}) {
    this.tagName = tagName.toUpperCase();
    this.id = attributes.id || "";
    this.className = attributes.class || "";
    this.children = [];
    this.parentNode = null;
    this.listeners = new Map();
    this.attributes = new Map(Object.entries(attributes));
    this.dataset = {};
    this.style = {
      setProperty(name, value) { this[name] = String(value); },
      getPropertyValue(name) { return this[name] === undefined ? "" : this[name]; },
    };
    this.hidden = Object.hasOwn(attributes, "hidden");
    this.disabled = false;
    this.value = attributes.value || "";
    this._textContent = "";
    this.classList = new FakeClassList(this);
    for (const [name, value] of Object.entries(attributes)) {
      if (name.startsWith("data-")) {
        const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        this.dataset[key] = value;
      }
    }
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join("");
    return this._textContent;
  }

  set textContent(value) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this._textContent = String(value ?? "");
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  append(...children) {
    for (const child of children) this.appendChild(child);
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this.className = String(value);
    if (name === "hidden") this.hidden = true;
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  dispatch(type, extra = {}) {
    const event = {
      type,
      target: this,
      preventDefault() { this.defaultPrevented = true; },
      defaultPrevented: false,
      ...extra,
    };
    for (const listener of this.listeners.get(type) || []) listener(event);
    return event;
  }

  click() {
    if (!this.disabled) this.dispatch("click", { detail: 1 });
  }

  getBoundingClientRect() {
    return { width: 600, height: 600, left: 0, top: 0, right: 600, bottom: 600 };
  }

  getContext() {
    return new Proxy({
      createRadialGradient: () => ({ addColor() {} }),
      measureText: () => ({ width: 0 }),
    }, {
      get(target, property) {
        if (property in target) return target[property];
        return () => {};
      },
      set(target, property, value) {
        target[property] = value;
        return true;
      },
    });
  }
}

class FakeTimers {
  constructor() {
    this.nextId = 1;
    this.timeouts = new Map();
    this.intervals = new Map();
  }

  setTimeout(callback, delay) {
    const id = this.nextId++;
    this.timeouts.set(id, { callback, delay: Number(delay) || 0 });
    return id;
  }

  clearTimeout(id) {
    this.timeouts.delete(id);
  }

  setInterval(callback, delay) {
    const id = this.nextId++;
    this.intervals.set(id, { callback, delay: Number(delay) || 0 });
    return id;
  }

  clearInterval(id) {
    this.intervals.delete(id);
  }

  runNextTimeout() {
    const entry = this.timeouts.entries().next();
    if (entry.done) return false;
    const [id, timer] = entry.value;
    this.timeouts.delete(id);
    timer.callback();
    return true;
  }

  get pendingTimeouts() {
    return this.timeouts.size;
  }
}

function createStorage(seed = {}) {
  const values = new Map(Object.entries(seed));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(String(key), String(value)); },
    removeItem(key) { values.delete(key); },
    dump() { return Object.fromEntries(values); },
  };
}

function parseElements(html) {
  const elements = new Map();
  const all = [];
  const pattern = /<([a-zA-Z][\w-]*)\b([^>]*)>/g;
  let match;
  while ((match = pattern.exec(html))) {
    const attributes = {};
    const attrPattern = /([\w:-]+)="([^"]*)"/g;
    let attr;
    while ((attr = attrPattern.exec(match[2]))) attributes[attr[1]] = attr[2];
    const element = new FakeElement(match[1], attributes);
    all.push(element);
    if (element.id) elements.set(element.id, element);
  }
  return { elements, all };
}

async function flush() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
}

function createHarness({ storage = {}, search = "" } = {}) {
  const html = fs.readFileSync(path.join(CLIENT, "index.html"), "utf8");
  const source = fs.readFileSync(path.join(CLIENT, "app.js"), "utf8");
  const { elements, all } = parseElements(html);
  const timers = new FakeTimers();
  const requests = [];
  const localStorage = createStorage(storage);
  const documentListeners = new Map();
  const windowListeners = new Map();

  const document = {
    hidden: false,
    getElementById(id) { return elements.get(id) || null; },
    querySelectorAll(selector) {
      if (selector === ".screen") return all.filter((element) => element.classList.contains("screen"));
      if (selector === "[data-action]") return all.filter((element) => element.dataset.action !== undefined);
      if (selector === "[data-dir]") return all.filter((element) => element.dataset.dir !== undefined);
      return [];
    },
    createElement(tag) { return new FakeElement(tag); },
    createTextNode(text) { return new FakeTextNode(text); },
    addEventListener(type, listener) {
      if (!documentListeners.has(type)) documentListeners.set(type, []);
      documentListeners.get(type).push(listener);
    },
    dispatch(type, extra = {}) {
      const event = { type, target: document, preventDefault() {}, ...extra };
      for (const listener of documentListeners.get(type) || []) listener(event);
      return event;
    },
  };

  const window = {
    devicePixelRatio: 1,
    location: { search },
    matchMedia() { return { matches: true }; },
    addEventListener(type, listener) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(listener);
    },
    dispatch(type, extra = {}) {
      const event = { type, target: window, preventDefault() {}, ...extra };
      for (const listener of windowListeners.get(type) || []) listener(event);
      return event;
    },
  };

  function fetch(url, options) {
    return new Promise((resolve, reject) => {
      requests.push({
        url: String(url),
        options,
        resolve(data, status = 200) {
          resolve({
            ok: status >= 200 && status < 300,
            status,
            async json() { return data; },
          });
        },
        reject,
      });
    });
  }

  const context = {
    window,
    document,
    localStorage,
    fetch,
    URL,
    URLSearchParams,
    Date,
    Math,
    JSON,
    console,
    performance: { now: () => Date.now() },
    setTimeout: timers.setTimeout.bind(timers),
    clearTimeout: timers.clearTimeout.bind(timers),
    setInterval: timers.setInterval.bind(timers),
    clearInterval: timers.clearInterval.bind(timers),
    requestAnimationFrame() { return 1; },
    cancelAnimationFrame() {},
  };

  vm.runInNewContext(source, context, { filename: "app.js" });

  return {
    elements,
    document,
    window,
    localStorage,
    timers,
    requests,
    flush,
    api: window.NeonArena,
    request(method, pathname) {
      return requests.findLast((entry) =>
        entry.options.method === method && new URL(entry.url).pathname === pathname);
    },
  };
}

function player(id = "P1", name = "You") {
  return {
    id,
    name,
    kind: "human",
    alive: true,
    pos: [1, 1],
    hp: 100,
    energy: 100,
    shield: 0,
    score: 0,
    hill_streak: 0,
    bounty_streak: 0,
  };
}

function matchView({ turn = 1, matchId = "match-1", submitted = false } = {}) {
  const now = Date.now();
  return {
    mode: "match",
    server: { now_ms: now },
    you: { id: "P1", name: "You" },
    match: {
      match_id: matchId,
      turn,
      turn_limit: 5,
      tick_ms: 10000,
      reply_by_ms: now + 10000,
      submitted,
      mode: "classic",
      seed: 7,
      rules: {
        max_hp: 100,
        max_energy: 100,
        dash: { cost: 20 },
        attack: { cost: 20 },
        shield: { cost: 20, max: 40 },
        heal: { cost: 20 },
      },
      players: [player()],
      arena: { width: 15, height: 15, walls: [], nodes: [] },
      nodes: [],
      events: [],
      mode_state: {},
    },
  };
}

function lobbyView({ name = "Lobby", startsInMs = null } = {}) {
  return {
    mode: "lobby",
    server: { now_ms: Date.now() },
    you: { id: "P1", name: "You" },
    lobby: {
      mode: "classic",
      mode_label: name,
      mode_description: "Description",
      min_players: 2,
      max_players: 4,
      players: [{ id: "P1", name: "You", kind: "human" }],
      starts_in_ms: startsInMs,
    },
  };
}

module.exports = {
  createHarness,
  flush,
  lobbyView,
  matchView,
  player,
};
