const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.isConnected = true;
    this.classList = {
      add: name => { this.className = `${this.className} ${name}`.trim(); },
      toggle: (name, enabled) => {
        if (enabled) this.classList.add(name);
      },
    };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.FTUI = {table: (headers, rows) => {
  const shell = new Element("div");
  shell.className = "table-shell";
  shell.headers = headers;
  shell.rows = rows;
  return {shell};
}};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/trading/workbench.js", "utf8",
), {filename: "trading/workbench.js"});

const paper = window.FTTradingWorkbench.connectionSnapshot({
  installed: true, engine_version: "2.0.0rc7",
  sandbox: {available: false, reason: "live data adapter not configured"},
  live: {available: false, reason: "venue execution adapter not configured"},
}, "paper");
assert.equal(paper.available, false);
assert.equal(paper.engine, "NautilusTrader 2.0.0rc7");
assert.deepEqual(paper.rows[1], ["模拟交易链路", "不可用", "未配置实时行情适配器"]);
assert.equal(paper.rows[0][1], "未报告", "runtime installation does not imply a connected feed");
const live = window.FTTradingWorkbench.connectionSnapshot({
  installed: true, live: {available: true},
}, "live");
assert.equal(live.available, true);
assert.deepEqual(live.rows[1], ["实盘交易链路", "服务端报告可用", "等待独立验收"]);
const inconsistent = window.FTTradingWorkbench.connectionSnapshot({
  installed: false, live: {available: true},
}, "live");
assert.equal(inconsistent.available, false, "missing runtime overrides a stale availability claim");
assert.deepEqual(inconsistent.rows[1], [
  "实盘交易链路", "不可用", "本服务尚未安装 NautilusTrader",
]);

const all = root => {
  const output = [root];
  for (const child of root.children || []) output.push(...all(child));
  return output;
};
const find = (root, predicate) => all(root).find(predicate);
const flush = () => new Promise(resolve => setImmediate(resolve));

function context(api) {
  const ctx = {
    paths: [], calls: [],
    toolbar: new Element("div"), content: new Element("div"),
    t: value => value,
    activeNav(value) { this.active = value; },
    setHeading(value) { this.heading = value; },
    navigate(path) { this.paths.push(path); },
    button(label, onClick) {
      const button = new Element("button");
      button.textContent = label;
      button.click = onClick;
      return button;
    },
    isRouteCurrent: () => true,
    api(path) { this.calls.push(path); return api(path); },
  };
  return ctx;
}

(async () => {
  const ctx = context(async () => ({installed: true, engine_version: "2.0.0rc7",
    sandbox: {available: false, reason: "live data adapter not configured"}}));
  window.FTTradingWorkbench.render(ctx, "paper");
  await flush();
  assert.equal(ctx.active, "trading");
  assert.deepEqual(ctx.calls, ["/api/nautilus/capabilities"]);
  assert.equal(find(ctx.content, item => item.className?.includes("trading-workbench-status"))
    .textContent, "不可用");
  const tables = all(ctx.content).filter(item => item.className === "table-shell");
  assert.equal(tables.length, 2, "the desk has connection and account views");
  assert.equal(tables[0].rows[1][0], "模拟交易链路");
  assert.deepEqual(tables[1].rows, [], "no account snapshot may be fabricated");
  assert.equal(find(ctx.content, item => /下单|买入|卖出/.test(item.textContent || "")
    && item.tagName === "BUTTON"), undefined);
  const liveTab = find(ctx.toolbar, item => item.textContent === "实盘");
  liveTab.click();
  assert.deepEqual(ctx.paths, ["/trading?mode=live"]);

  const pending = [];
  const racing = context(() => new Promise(resolve => pending.push(resolve)));
  window.FTTradingWorkbench.render(racing, "live");
  const refresh = find(racing.content, item => item.textContent === "刷新状态");
  refresh.click();
  assert.equal(pending.length, 2);
  pending[1]({installed: true, live: {available: false, reason: "venue execution adapter not configured"}});
  await flush();
  pending[0]({installed: true, live: {available: true}});
  await flush();
  assert.equal(find(racing.content, item => item.className?.includes("trading-workbench-status"))
    .textContent, "不可用", "an older response must not overwrite the latest refresh");

  const unreachable = context(async () => { throw new Error("service unavailable"); });
  window.FTTradingWorkbench.render(unreachable, "live");
  await flush();
  assert.equal(find(unreachable.content, item => item.className?.includes("trading-workbench-status"))
    .textContent, "无法读取");
  console.log("nautilus trading workbench contract passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
