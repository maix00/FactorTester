import assert from "node:assert/strict";
import test from "node:test";
import { appendStrategy, patchStrategy, configurationStrategies, strategyDefaults, strategySchema, TEMPLATE_PATH, LIBRARY_PATH, type StrategyChoice } from "./strategies.ts";
import { parseDraft, readPath } from "./draft.ts";

const choice: StrategyChoice = { strategy_ref: "public:group", template_ref: "public:group", revision_ref: "public:group:1", name: "Group",
  configuration_schema: { fields: [
    { key: "signal", label: "Signal", type: "factor_ref", required: true },
    { key: "product_group_ref", label: "Products", type: "product_group_ref", required: true },
    { key: "split_count", label: "Count", type: "integer", default: 5 },
    { key: "group_index", label: "Index", type: "integer", default: 1, maximum_from: "split_count" },
  ] } };
const factor = { schema_version: 2, ref: "factor:v2:example", identity: { immutable: true } };
const text = JSON.stringify({ shared: { factors: [] }, analyses: {}, extension: { preserve: [0, false, null] } });

test("strategy metadata supplies defaults, required roles and dependent bounds", () => {
  assert.deepEqual(strategyDefaults(choice), { split_count: 5, group_index: 1 });
  const schema = strategySchema(choice, { split_count: 8 });
  assert.deepEqual(schema.required, ["signal", "product_group_ref"]);
  assert.equal((schema.properties as any).group_index.maximum, 8);
});

test("public strategy owns factor bindings and retains frozen dependencies and extensions", () => {
  const value = parseDraft(appendStrategy(text, choice, { signal: factor.ref, product_group_ref: "products:treasuries", split_count: 5, group_index: 1 }, "group-1", [factor])).value!;
  const bindings = readPath(value, TEMPLATE_PATH) as any[];
  assert.deepEqual(bindings[0].factor_bindings, { signal: factor.ref });
  assert.deepEqual(bindings[0].parameters, { split_count: 5, group_index: 1 });
  assert.deepEqual(readPath(value, LIBRARY_PATH), []);
  assert.deepEqual(value.extension, { preserve: [0, false, null] });
  assert.deepEqual(readPath(value, ["shared", "factors"]), [factor]);
});

test("library strategies pin exact revision and reject duplicate target IDs", () => {
  const library: StrategyChoice = { name: "Custom", strategy_ref: "strategy:custom", current_revision: { revision_ref: "revision:2", source_sha256: "digest" } };
  const next = appendStrategy(text, library, {}, "custom-1", []);
  const value = parseDraft(next).value!;
  assert.deepEqual((readPath(value, LIBRARY_PATH) as any[])[0].source, { kind: "library", strategy_ref: "strategy:custom", revision_ref: "revision:2", source_sha256: "digest" });
  assert.throws(() => appendStrategy(next, choice, {}, "custom-1", []), /Duplicate/);
  assert.throws(() => appendStrategy(text, { name: "Missing", strategy_ref: "strategy:missing" }, {}, "missing", []), /revision/);
});

test("adding a strategy never overwrites a richer configuration-local frozen factor", () => {
  const rich = { ...factor, temporary: true, source_code: "source" };
  const next = JSON.stringify({ shared: { factors: [rich] }, analyses: {} });
  const result = parseDraft(appendStrategy(next, choice, { signal: factor.ref }, "test", [factor])).value!;
  assert.deepEqual(readPath(result, ["shared", "factors"]), [rich]);
});

test("strategy edits preserve binding identity, ordering, and unrelated fields", () => {
  const first = appendStrategy(text, choice, {}, "first", []);
  const second = appendStrategy(first, choice, {}, "second", []);
  const edited = patchStrategy(second, "tr-strategy-binding:first", { parameters: { group_index: 2 }, binding_id: "wrong" });
  const records = configurationStrategies(edited);
  assert.deepEqual(records.map(({ binding }) => binding.binding_id), ["tr-strategy-binding:first", "tr-strategy-binding:second"]);
  assert.deepEqual(records[0].binding.parameters, { group_index: 2 });
  assert.equal(patchStrategy(edited, "missing", {}), edited);
  assert.deepEqual(parseDraft(edited).value!.extension, { preserve: [0, false, null] });
});
