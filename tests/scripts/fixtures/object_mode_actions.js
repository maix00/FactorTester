"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
window.FTUI = {
  iconButton(context, symbol, label, handler) {
    return {
      symbol, label,
      title: context.t ? context.t(label) : label,
      onclick: handler,
    };
  },
  actionButton(label, handler) {
    return {textContent: label, title: label, onclick: handler};
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
  const element = {children: [], append(...items) { this.children.push(...items); }};
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

// view mode: pencil icon action navigates to the same-tab edit href.
(() => {
  const ctx = context();
  const actions = window.FTObjectModeActions.mount(ctx, {
    mode: "view",
    onEdit: true,
    editHref: "/factors/factor/A%7CTh%3A5?mode=edit",
    editLabel: "编辑",
  });
  assert.equal(ctx.toolbar.children.length, 1);
  const action = ctx.toolbar.children[0];
  assert.equal(action.symbol, "square.and.pencil", "edit icon matches the catalog table set");
  assert.equal(action.title, "编辑", "localized tooltip");
  action.onclick();
  assert.equal(ctx._navigated, "/factors/factor/A%7CTh%3A5?mode=edit");
  assert.equal(actions.length, 1);
})();

// view mode without editHref: derive from the location (same pathname → same
// tab swap even for frozen/alias view URLs).
(() => {
  window.FTPageMode = {
    hrefForMode: mode => `/factors/factor/factor%3Av2%3Astored?mode=${mode}`,
  };
  const ctx = context();
  window.FTObjectModeActions.mount(ctx, {mode: "view", onEdit: true});
  assert.equal(ctx.toolbar.children.length, 1);
  ctx.toolbar.children[0].onclick();
  assert.equal(
    ctx._navigated, "/factors/factor/factor%3Av2%3Astored?mode=edit",
  );
  delete window.FTPageMode;
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
  assert.equal(ctx.toolbar.children[0].symbol, "xmark");
  assert.equal(ctx.toolbar.children[1].symbol, "checkmark.circle");
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
  assert.equal(ctx.toolbar.children[1].title, "提交");
})();

// overlay create: save label stays 保存.
(() => {
  const ctx = context({testObjectOverlay: true});
  window.FTObjectModeActions.mount(ctx, {
    mode: "create",
    onCancel: () => {},
    onSave: () => {},
    overlaySaveLabel: "保存",
  });
  assert.equal(ctx.toolbar.children[1].title, "保存");
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
