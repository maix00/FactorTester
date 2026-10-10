const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.className = "";
  }
  append(...items) { this.children.push(...items); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  replaceChildren(...items) { this.children = items; }
}

global.window = {};
global.document = {createElement: tagName => new Element(tagName)};
global.FTUI = {
  userDisplay: value => String(value || ""),
  pagedTable(headers, items, options) {
    const shell = new Element("table");
    const body = {rows: items.map(item => {
      const row = new Element("tr");
      row.values = options.renderRow(item);
      return row;
    })};
    shell.body = body;
    return {
      shell,
      body,
      start: 0,
      pageSize: 20,
      headers,
    };
  },
};
window.FTFactorModel = {
  familyName: item => item.factor_family_name || item.factor_family_alias,
  description: item => item.description || "",
  owner: item => item.owner_username,
  productGroupNames: () => new Map(),
  subjectGroups: () => new Map(),
  productGroupRefs: () => [],
  groupLabels: () => [],
  matches: () => true,
};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-list.js", "utf8"),
  {filename: "factor-list.js"},
);

const navigated = [];
const mount = new Element("main");
const factorRef = `factor:v2:${"a".repeat(43)}`;
const familyRef = `factor-family:v2:${"b".repeat(43)}`;
window.FTFactorList.render({
  t: value => value,
  navigate: path => navigated.push(path),
}, {
  principal: "alice",
  groups: [],
  families: [{
    family_ref: familyRef,
    factor_family_alias: "PublicFamily",
    owner_username: "bob",
    factor_kind: "custom",
  }],
  factors: [{
    factor_ref: factorRef,
    factor_alias: "RegisteredPublicFactor",
    owner_username: "bob",
    factor_family_alias: "PublicFamily",
    family_ref: familyRef,
    factor_kind: "registered",
    source: "registered",
  }],
}, mount, {
  page: "factors",
  query: "",
  groupRefs: ["*"],
  ownerUsernames: ["*"],
  scope: "subordinates",
  tablePage: 1,
});

const row = mount.children[0].body.rows[0];
assert.ok(row.listeners.click, "a factor row should remain navigable");
row.listeners.click();
assert.strictEqual(
  navigated[0], `/factors/factor/${encodeURIComponent(factorRef)}?owner_username=bob`,
);
console.log("ok");
