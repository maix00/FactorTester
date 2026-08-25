const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.className = "";
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
}

global.document = {createElement: () => new Element()};
global.window = {};
global.FTUI = window.FTUI = {
  loading: value => Object.assign(new Element(), {textContent: value}),
  empty: () => new Element(),
  formatDate: value => String(value),
  pagedTable(_headers, rows, options) {
    const shell = new Element();
    const body = {rows: rows.map(() => new Element())};
    shell.body = body;
    return {shell, body, options};
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/shared/object-job-table.js", "utf8"),
  {filename: "object-job-table.js"},
);

const requests = [];
const navigations = [];
const context = {
  t: value => value,
  session: {role: "user"},
  async api(path) {
    requests.push(path);
    return {
      jobs: [{job_id: "job-1", task_name: "回测", status: "succeeded"}],
      page: 1, page_size: 20, total: 1,
    };
  },
  navigate: path => navigations.push(path),
  button: () => new Element(),
};
const table = window.FTFactorObjectJobs.create(context, {
  objectKind: "family",
  objectRef: "factor-family:v2:current",
  ownerRef: "principal:alice",
  alias: "Momentum",
});
assert.deepStrictEqual(requests, []);

(async () => {
  await table.load();
  assert.strictEqual(requests.length, 1);
  const query = new URL(requests[0], "https://example.invalid").searchParams;
  assert.strictEqual(query.get("scope"), "visible");
  assert.strictEqual(query.get("object_kind"), "family");
  assert.strictEqual(query.get("object_owner_ref"), "principal:alice");
  assert.strictEqual(query.get("object_alias"), "Momentum");
  table.mount.children[0].body?.rows?.[0]?.listeners?.click?.();
  assert.deepStrictEqual(navigations, ["/jobs/job-1"]);
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
