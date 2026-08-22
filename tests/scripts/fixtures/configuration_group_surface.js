const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

function find(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children || []) {
    const result = find(child, predicate);
    if (result) return result;
  }
  return null;
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.confirm = () => true;
global.FTUI = {
  empty: (title, copy) => {
    const node = new Element("empty");
    node.textContent = `${title}: ${copy}`;
    return node;
  },
};
global.FTTabListChip = {
  create: options => {
    const root = new Element("section");
    const shell = new Element("div");
    const title = new Element("h2");
    title.textContent = options.title;
    root.append(title);
    for (const action of options.actionsFor(options.activeKey) || []) {
      const button = new Element("button");
      button.textContent = action.label;
      button.disabled = action.disabled;
      button.listeners.click = action.onClick;
      root.append(button);
    }
    for (const item of options.items) root.append(item.render());
    root.append(shell);
    return {root, shell};
  },
};

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "configuration-group-surface.js",
});
global.FTConfigurationGroupSurface = window.FTConfigurationGroupSurface;

let initialized = 0;
let removed = 0;
let refreshed = 0;
const state = {
  kind: "ic",
  selectedIDs: [],
  manifest: {
    surfaces: [{
      key: "ic_configs", label: "配置组设置", mount: "group-settings",
      kind: "list", selection: "single", item_label: "配置组",
      content_adapter: "ic_configuration_groups",
    }],
    flows: [
      {surface: "ic_configs", key: "add", label: "新增配置组", kind: "create"},
      {surface: "ic_configs", key: "delete", label: "删除", kind: "delete", min_selected: 1},
    ],
  },
};
const adapters = {
  ic_configuration_groups: {
    render: () => {
      const node = new Element("list"); node.textContent = "groups"; return node;
    },
    selected: value => value.selectedIDs.map(id => ({id})),
    removeSelected: value => { removed += 1; value.selectedIDs = []; },
    actions: {create: () => ({mode: "create"})},
  },
};
const options = {
  context: {t: value => value}, state,
  refresh: () => { refreshed += 1; }, adapters,
  initialize: () => { initialized += 1; },
  title: "配置组设置", description: "同一任务中的配置组", count: "0 个配置组",
  activeKey: "activeGroupSurface", openKey: "groupSurfaceOpen", editorKey: "groupEditor",
  renderEditor: (_context, _state, editor) => {
    const form = new Element("form"); form.textContent = editor.mode; return form;
  },
};

let root = FTConfigurationGroupSurface.render(options);
assert.equal(initialized, 1);
assert.equal(find(root, node => node.tagName === "h2").textContent, "配置组设置");
const create = find(root, node => node.tagName === "button" && node.textContent === "新增配置组");
assert.ok(create);
create.listeners.click();
assert.deepEqual(state.groupEditor, {mode: "create"});
assert.equal(refreshed, 1);
root = FTConfigurationGroupSurface.render(options);
assert.equal(find(root, node => node.tagName === "form").textContent, "create");

state.selectedIDs = ["cfg-1"];
root = FTConfigurationGroupSurface.render(options);
const remove = find(root, node => node.tagName === "button" && node.textContent === "删除");
assert.equal(remove.disabled, false);
remove.listeners.click();
assert.equal(removed, 1);
assert.deepEqual(state.selectedIDs, []);

const renderer = {render: () => new Element("registered")};
FTConfigurationGroupSurface.register("ic", renderer);
assert.equal(FTConfigurationGroupSurface.renderer("ic"), renderer);
assert.throws(() => FTConfigurationGroupSurface.register("ic", renderer), /already registered/);

console.log("ok");
