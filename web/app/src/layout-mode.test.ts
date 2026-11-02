import test from "node:test";
import assert from "node:assert/strict";
import { mobileLayout } from "./layout-mode.ts";

test("mobile shell survives a landscape reload without changing desktop selection", () => {
  assert.equal(mobileLayout(false, "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", "iPhone", 5), true);
  assert.equal(mobileLayout(false, "Mozilla/5.0 (Linux; Android 15; Pixel)", "Linux", 5), true);
  assert.equal(mobileLayout(false, "Mozilla/5.0 (Macintosh; Intel Mac OS X)", "MacIntel", 5), true);
  assert.equal(mobileLayout(false, "Mozilla/5.0 (Macintosh; Intel Mac OS X)", "MacIntel", 0), false);
  assert.equal(mobileLayout(false, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Win32", 10), false);
  assert.equal(mobileLayout(true, "Mozilla/5.0", "Win32", 0), true);
});
