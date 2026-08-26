const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag, attributes = {}) {
    this.tagName = tag.toUpperCase();
    this.attributes = {...attributes};
    this.type = attributes.type || "";
    this.name = attributes.name || "";
    this.value = attributes.value || "";
    this.textContent = attributes.text || "";
    this.innerText = this.textContent;
    this.hidden = false;
    this.disabled = false;
    this.required = Boolean(attributes.required);
    this.checked = false;
    this.style = {};
    this.parentElement = null;
    this.events = [];
    this.clicked = false;
    this.options = attributes.options || [];
    this.multiple = Boolean(attributes.multiple);
    this.id = attributes.id || "";
    this.href = attributes.href || "";
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  closest() { return null; }
  dispatchEvent(event) { this.events.push(event.type); }
  click() { this.clicked = true; }
  matches(selector) {
    return selector.split(",").some(raw => {
      const value = raw.trim();
      if (value === "input") return this.tagName === "INPUT";
      if (value === "select") return this.tagName === "SELECT";
      if (value === "select[multiple]") return this.tagName === "SELECT" && this.multiple;
      if (value === "textarea") return this.tagName === "TEXTAREA";
      if (value === "button") return this.tagName === "BUTTON";
      if (value === "a[href]") return this.tagName === "A" && Boolean(this.attributes.href);
      if (value === "[contenteditable=true]") return this.attributes.contenteditable === "true";
      return false;
    });
  }
}

const factor = new Element("input", {name: "factor", value: "old", text: "Factor"});
const password = new Element("input", {name: "password", value: "secret", type: "password"});
const run = new Element("button", {text: "Run test", type: "submit"});
const external = new Element("a", {text: "External", href: "https://example.com"});
const controls = [factor, password, run, external];
const subordinate = new Element("input", {name: "parent_username", value: "manager-1"});
const dialog = {querySelectorAll: () => [subordinate]};
const root = {
  innerText: "IC test Factor Run test",
  textContent: "IC test Factor Run test",
  querySelectorAll: () => controls,
};
const registrations = new Map();
const documentElement = new Element("html");

global.Event = class Event { constructor(type) { this.type = type; } };
global.DOMException = class DOMException extends Error {};
global.CSS = {escape: value => value};
global.location = {
  origin: "https://factortester.local", href: "https://factortester.local/ic-test",
  pathname: "/ic-test", search: "",
};
global.document = {
  documentElement,
  title: "FactorTester",
  modelContext: {registerTool: tool => registrations.set(tool.name, tool)},
  getElementById: () => null,
  querySelector: selector => selector === "#page-title" ? {textContent: "IC 测试"} : null,
  querySelectorAll: selector => selector.includes("dialog[open]") ? [dialog] : [],
};
global.window = {
  requestAnimationFrame: callback => callback(),
};

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/app/webmcp.js", "utf8",
), {filename: "webmcp.js"});

(async () => {
  const navigated = [];
  const result = window.FTWebMCP.bind({
    navigate: path => navigated.push(path), root,
    session: () => ({role: "super_admin"}),
  });
  assert.equal(result.supported, true);
  assert.deepEqual([...registrations.keys()], [
    "factortester_capabilities", "factortester_open_surface",
    "factortester_inspect_surface", "factortester_fill_form",
    "factortester_activate",
  ]);

  const capabilities = await registrations.get("factortester_capabilities").execute({query: "subordinate"});
  assert.equal(capabilities.surfaces[0].id, "manager_accounts");
  assert.equal(capabilities.authenticated, true);

  await registrations.get("factortester_open_surface").execute({surface: "backtest"}, {});
  assert.deepEqual(navigated, ["/backtest"]);

  const inspected = await registrations.get("factortester_inspect_surface").execute({});
  assert.equal(inspected.fields.length, 3, "open management dialogs must be inspectable");
  assert.equal(inspected.actions.length, 2);
  assert.equal(inspected.fields[1].sensitive, true);
  assert.equal("value" in inspected.fields[1], false, "password values must not leave the page");

  const filled = await registrations.get("factortester_fill_form").execute({
    fields: {[inspected.fields[0].id]: "SgCCS"},
  });
  assert.equal(factor.value, "SgCCS");
  assert.deepEqual(factor.events, ["input", "change"]);
  assert.equal(filled.changed[0].id, "field-1");

  await registrations.get("factortester_activate").execute({
    action: inspected.actions[0].id, confirmed: true,
  }, {});
  assert.equal(run.clicked, true);

  await assert.rejects(
    registrations.get("factortester_activate").execute({
      action: inspected.actions[1].id, confirmed: true,
    }, {}),
    /external links/,
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
