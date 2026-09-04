"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
window.FTUI = {
  actionButton(label, handler) {
    return {textContent: label, title: "", onclick: handler};
  },
};
vm.runInThisContext(
  fs.readFileSync(
    "server/manager/web/catalog/shared/object-mode-actions.js",
    "utf8",
  ),
  {filename: "object-mode-actions.js"},
);

function toolbar() {
  const element = {
    children: [],
    append(...items) { this.children.push(...items); },
  };
  return element;
}

function context(extra = {}) {
  const ctx = {
    toolbar: toolbar(),
    t: value => value,
    navigate(path) { this._navigated = path; },
    isRouteCurrent: () => true,
    ...extra,
  };
  return ctx;
}

// view mode: an onEdit entry navigates to the same-tab edit href.
(() => {
  const ctx = context();
  window.FTObjectModeActions.mount(ctx, {
    mode: "view",
    onEdit: true,
    editHref: "/factors/factor/A%7CTh%3A5?mode=edit",
    editLabel: "编辑",
  });
  assert.equal(ctx.toolbar.children.length, 1);
  ctx.toolbar.children[0].onclick();
  assert.equal(ctx._navigated, "/factors/factor/A%7CTh%3A5?mode=edit");
})();

// view mode: no edit action when testObjectViewOnly.
(() => {
  const ctx = context({testObjectViewOnly: true});
  window.FTObjectModeActions.mount(ctx, {
    mode: "view", onEdit: true,
    editHref: "/factors/factor/A?mode=edit",
  });
  assert.equal(ctx.toolbar.children.length, 0);
})();

// edit mode (not temporary): cancel navigates back to the same tab's view.
(() => {
  const ctx = context();
  const actions = window.FTObjectModeActions.mount(ctx, {
    mode: "edit",
    viewHref: "/factors/factor/A%7CTh%3A5",
    onSave: () => {},
  });
  assert.equal(ctx.toolbar.children.length, 2);
  ctx.toolbar.children[0].onclick(); // cancel
  assert.equal(ctx._navigated, "/factors/factor/A%7CTh%3A5");
  assert.equal(actions.length, 2);
})();

// create mode: cancel uses onCancel (placeholder tab), save label 提交.
(() => {
  let cancelled = 0;
  const ctx = context();
  window.FTObjectModeActions.mount(ctx, {
    mode: "create",
    onCancel: () => { cancelled += 1; },
    onSave: () => {},
  });
  assert.equal(ctx.toolbar.children.length, 2);
  ctx.toolbar.children[0].onclick();
  assert.equal(cancelled, 1);
  assert.equal(ctx.toolbar.children[1].textContent, "提交");
})();

// route-session guard: expired session must not append to the header.
(() => {
  const ctx = context({isRouteCurrent: () => false});
  const actions = window.FTObjectModeActions.mount(ctx, {
    mode: "edit",
    viewHref: "/factors/factor/A",
    onSave: () => {},
  });
  assert.equal(ctx.toolbar.children.length, 0);
  assert.equal(actions.length, 2, "actions still returned for busy-state use");
})();

console.log("ok");
