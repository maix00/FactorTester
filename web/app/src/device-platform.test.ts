import assert from "node:assert/strict";
import test from "node:test";
import { devicePlatform, deviceUsernames } from "./device-platform.ts";

test("admin device filters derive a stable distinct user list from registered devices", () => {
  assert.deepEqual(deviceUsernames([
    { username: "zhao" }, { username: "li" }, { username: "zhao" }, { username: " " }, {},
  ]), ["li", "zhao"]);
});

test("device client classification keeps web, native, mobile and CLI identities distinct", () => {
  assert.equal(devicePlatform({ client_type: "browser", client_name: "Safari" }), "web");
  assert.equal(devicePlatform({ client_type: "swift", client_name: "TradeResearch" }), "desktop");
  assert.equal(devicePlatform({ client_type: "mobile", client_name: "iOS" }), "mobile");
  assert.equal(devicePlatform({ client_type: "cli-python" }), "cli");
});
