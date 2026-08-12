const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-model.js", "utf8"),
  {filename: "factor-model.js"},
);

const model = window.FTFactorModel;
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

const encodedPath = Buffer.from("public_factors/MmRateOfChg.py").toString("base64url");
const encodedAlias = Buffer.from("MmRateOfChg|P:[CA]|N:20d|$F:3d|$Rev").toString("base64url");
const target = `factor:v1:profile-maxa:${encodedPath}:${encodedAlias}:${"a".repeat(40)}:${"b".repeat(40)}`;
assert.deepStrictEqual(model.decodeFrozenFactorRef(target), {
  factorRef: target,
  alias: "MmRateOfChg|P:[CA]|N:20d|$F:3d|$Rev",
  family: "MmRateOfChg",
  ownerRef: "profile:maxa",
  gitCommit: "a".repeat(40),
  gitBlob: "b".repeat(40),
  relativePath: "public_factors/MmRateOfChg.py",
  params: [
    {alias: "P", value: "[CA]", redacted: false},
    {alias: "N", value: "20d", redacted: false},
    {alias: "$F", value: "3d", redacted: false},
    {alias: "$Rev", value: "", redacted: false},
  ],
});
console.log("ok");
