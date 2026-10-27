import assert from "node:assert/strict";
import test from "node:test";
import { createDraft } from "./draft.ts";
import { runRequest } from "./run.ts";

test("run requests reference the saved workspace revision and require a strategy", () => {
  const draft = createDraft({ analyses: { backtest: { strategy_bindings: [{ target_strategy_id: "s" }] } } }, 4);
  assert.deepEqual(runRequest("w", draft), { workspace_id: "w", configuration_revision: 4, analyses: ["backtest"] });
  assert.throws(() => runRequest("w", { ...draft, text: "{}" }), /Save/);
  assert.throws(() => runRequest("w", createDraft({}, 1)), /strategy/);
});


test("factor tests submit their selected analysis without requiring a trading strategy", () => {
  const draft = createDraft({ analyses: { ic: { configuration_groups: [{ factor_ref: "factor:v2:fixture" }] } } }, 7);
  assert.deepEqual(runRequest("w", draft, "ic"), { workspace_id: "w", configuration_revision: 7, analyses: ["ic"] });
  assert.throws(() => runRequest("w", { ...draft, text: "{}" }, "ic"), /Save/);
});
