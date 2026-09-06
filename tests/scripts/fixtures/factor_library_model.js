const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-model.js", "utf8"),
  {filename: "factor-model.js"},
);

const model = window.FTFactorModel;
assert.strictEqual(
  model.factorExpression(
    {math_expr: "TEMPLATE", resolved_math_expr: "BACKEND"},
    {instance: true, resolvedOnly: true},
  ),
  "BACKEND",
);
assert.strictEqual(
  model.factorExpression(
    {math_expr: "TEMPLATE"},
    {instance: true, resolvedOnly: true},
  ),
  "",
  "view mode must not fall back to the editor template",
);
const group = {
  group_ref: "product-group:local-one",
  name: "本地组",
  factor_refs: ["factor:one"],
  factor_set_refs: ["factor-set:stable"],
};
const groupNames = model.productGroupNames([group]);
const bySubject = model.subjectGroups([group]);
assert.strictEqual(groupNames.get("product-group:local-one"), "本地组");
assert.deepStrictEqual(
  model.productGroupRefs({kind: "factor", value: {factor_ref: "factor:one"}}, bySubject),
  ["product-group:local-one"],
);
assert.deepStrictEqual(
  model.productGroupRefs({
    kind: "factor-set",
    value: {target_ref: "factor-set:frozen", set_ref: "factor-set:stable"},
  }, bySubject),
  ["product-group:local-one"],
);

const target = `factor:v2:${"A".repeat(43)}`;
const frozen = {
  schema_version: 2,
  ref: target,
  alias: "MmRateOfChg|P:CA|N:20d|$F:3d|$Rev",
  owner_ref: "profile:maxa",
  identity: {
    family_ref: `factor-family:v2:${"B".repeat(43)}`,
    family_alias: "MmRateOfChg",
    family_formula_fingerprint: "a".repeat(64),
    self_formula_fingerprint: "b".repeat(64),
    params: {P: "CA", N: "20d", $F: "3d", $Rev: ""},
  },
};
assert.deepStrictEqual(model.frozenFactorIdentity(frozen), {
  factorRef: target,
  alias: "MmRateOfChg|P:CA|N:20d|$F:3d|$Rev",
  family: "MmRateOfChg",
  ownerRef: "profile:maxa",
  familyFormulaFingerprint: "a".repeat(64),
  selfFormulaFingerprint: "b".repeat(64),
  record: frozen,
  params: {P: "CA", N: "20d", $F: "3d", $Rev: ""},
});
assert.deepStrictEqual(model.objectChoice(frozen), {
  value: target,
  label: "MmRateOfChg|P:CA|N:20d|$F:3d|$Rev",
  record: frozen,
});
assert.deepStrictEqual(model.frozenFactorIdentity({
  factor_ref: target,
  factor_alias: frozen.alias,
  factor_owner_ref: frozen.owner_ref,
  factor_family_alias: frozen.identity.family_alias,
  family_formula_fingerprint: frozen.identity.family_formula_fingerprint,
  self_formula_fingerprint: frozen.identity.self_formula_fingerprint,
  params: [
    {alias: "P", value: "CA", redacted: false},
    {alias: "N", value: "20d", redacted: false},
    {alias: "$F", value: "3d", redacted: false},
    {alias: "$Rev", value: "", redacted: false},
  ],
}), null);
console.log("ok");
