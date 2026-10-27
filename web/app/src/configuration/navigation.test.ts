import assert from "node:assert/strict";
import test from "node:test";
import { configurationURL, readConfigurationView } from "./navigation.ts";

test("configuration navigation round-trips paths and keeps unrelated route state", () => {
  const url = new URL(configurationURL("http://localhost/app?workspace_id=w&locale=en", { page: "field", path: ["analyses", "backtest", "execution", "settings", "data_source"] }));
  assert.equal(url.searchParams.get("workspace_id"), "w");
  assert.deepEqual(readConfigurationView(url.search), { page: "field", id: undefined, path: ["analyses", "backtest", "execution", "settings", "data_source"] });
  assert.deepEqual(readConfigurationView("?tr_config=unknown"), { page: "overview" });
  assert.equal(new URL(configurationURL(url.href, { page: "overview" })).searchParams.has("tr_path"), false);
});
