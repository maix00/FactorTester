import assert from "node:assert/strict";
import test from "node:test";
import { BUILTIN_PAGES, getPage, pagesForAdminCapabilities, pagesForScope, registerPage } from "./registry.ts";

test("builtin pages preserve desktop/mobile scopes", () => {
  for (const page of BUILTIN_PAGES) registerPage(page);
  assert.equal(getPage("more")?.scope, "mobile");
  const desktop = pagesForScope("desktop").filter((page) => page.sidebarVisible !== false);
  assert.ok(["products", "factors", "strategies", "jobs"].every((id) => desktop.some((page) => page.id === id)));
  assert.ok(!desktop.some((page) => page.id === "account" || page.id === "settings"));
  assert.deepEqual(pagesForScope("mobile").filter((page) => page.mobileTab).map((page) => page.id), ["research", "configuration", "trading", "more"]);
});

test("duplicate page ids are rejected", () => {
  assert.throws(() => registerPage(BUILTIN_PAGES[0]), /duplicate page id/);
});

test("admin-only pages are hidden until the matching Keycloak capability is present", () => {
  assert.ok(!pagesForAdminCapabilities("desktop").some((page) => page.id === "admin"));
  assert.ok(!pagesForAdminCapabilities("mobile", ["admin_console:read"]).some((page) => page.id === "admin"));
  assert.ok(pagesForAdminCapabilities("desktop", ["admin_console:manage"]).some((page) => page.id === "admin"));
  assert.ok(pagesForAdminCapabilities("mobile", ["admin_console:manage"]).some((page) => page.id === "admin"));
});

test("every registered page has a title, icon and route", () => {
  for (const page of BUILTIN_PAGES) {
    assert.ok(page.title.length > 0);
    assert.ok(page.icon);
    assert.ok(page.icon.length > 0);
    assert.match(page.route, /^\//);
  }
  assert.ok(pagesForScope("mobile").some((page) => page.id === "settings"));
  assert.ok(!pagesForScope("desktop").some((page) => page.id === "account"));
});
