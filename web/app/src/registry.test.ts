import assert from "node:assert/strict";
import test from "node:test";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";

test("builtin pages preserve desktop/mobile scopes", () => {
  for (const page of BUILTIN_PAGES) registerPage(page);
  assert.equal(getPage("workspace")?.scope, "mobile");
  assert.ok(pagesForScope("desktop").some((page) => page.id === "catalog"));
  assert.ok(!pagesForScope("mobile").some((page) => page.id === "catalog"));
});

test("duplicate page ids are rejected", () => {
  assert.throws(() => registerPage(BUILTIN_PAGES[0]), /duplicate page id/);
});

test("every registered page has a title, icon and route", () => {
  for (const page of BUILTIN_PAGES) {
    assert.ok(page.title.length > 0);
    assert.ok(page.icon);
    assert.ok(page.icon.length > 0);
    assert.match(page.route, /^\//);
  }
  assert.ok(pagesForScope("mobile").some((page) => page.id === "settings"));
  assert.ok(pagesForScope("desktop").some((page) => page.id === "account"));
});
