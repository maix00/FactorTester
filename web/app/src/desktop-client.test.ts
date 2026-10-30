import test from "node:test";
import assert from "node:assert/strict";
import { hasDesktopClientBridge } from "./desktop-client.ts";

test("ordinary browsers and mobile WebKit do not identify as desktop clients", () => {
  assert.equal(hasDesktopClientBridge(undefined), false);
  assert.equal(hasDesktopClientBridge({ navigator: { userAgent: "Mozilla Mac" } }), false);
  assert.equal(hasDesktopClientBridge({ webkit: { messageHandlers: { clientAuthentication: { postMessage() {} } } } }), false);
  assert.equal(hasDesktopClientBridge({ webkit: { messageHandlers: { factorTesterLocalRun: { postMessage() {} } } } }), false);
});

test("the current macOS client exposes both local handlers", () => {
  const handler = { postMessage() {} };
  assert.equal(hasDesktopClientBridge({ webkit: { messageHandlers: { factorTesterLocalRun: handler, factorTesterLocalCatalog: handler } } }), true);
});
