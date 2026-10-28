import assert from "node:assert/strict";
import test from "node:test";
import { settingsSection } from "./settings-navigation.ts";

test("navigation groups metadata without dropping new registered tabs", () => {
  assert.equal(settingsSection("data_source"), "data");
  assert.equal(settingsSection("order"), "execution");
  assert.equal(settingsSection("margin"), "funds");
  assert.equal(settingsSection("future_registered_tab"), "other");
});
