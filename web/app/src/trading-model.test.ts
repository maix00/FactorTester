import assert from "node:assert/strict";
import test from "node:test";
import { tradingSnapshot } from "./trading-model.ts";
test("trading never invents adapter or account readiness from engine installation", () => {
  assert.equal(tradingSnapshot({ installed: true }, "paper").reported, false);
  assert.equal(tradingSnapshot({ installed: false, sandbox: { available: true } }, "paper").available, false);
  assert.equal(tradingSnapshot({ installed: true, sandbox: { available: true }, live: { available: false } }, "paper").available, true);
  assert.equal(tradingSnapshot({ installed: true, sandbox: { available: true }, live: { available: false } }, "live").available, false);
  assert.equal(tradingSnapshot({ installed: true, live: { available: false, reason: "venue execution adapter not configured" } }, "live").reason, "venue execution adapter not configured");
});
