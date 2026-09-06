const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

global.window = {};
vm.runInThisContext(fs.readFileSync(path.join(
  __dirname, "../../../server/manager/web/catalog/factor-editor.js",
), "utf8"), {filename: "factor-editor.js"});

const calls = [];
const context = {
  t: value => value,
  session: {username: "alice"},
  async api(endpoint, options) {
    const body = JSON.parse(options.body);
    calls.push(body);
    const alias = body.source_code ? "InlineChild|N:5d" : "LibraryLeaf|N:2d";
    return {
      valid: true,
      factor_family_alias: body.source_code ? "InlineChild" : "LibraryLeaf",
      params: [],
      factor: {
        schema_version: 2,
        ref: `factor:v2:${calls.length}`,
        alias,
        owner_ref: "alice",
        identity: {
          family_alias: alias.split("|", 1)[0],
          family_formula_fingerprint: "a".repeat(64),
          self_formula_fingerprint: "b".repeat(64),
          params: {},
        },
      },
    };
  },
};

(async () => {
  const values = await window.FTFactorEditor.materializeFamilyDrafts(context, {
    P: {
      __factor_family_draft: true,
      __factor_family: {
        factor_family_alias: "InlineChild",
        source_code: "class InlineChild: pass",
        source_kind: "transient",
        temporary: true,
      },
      parameter_values: {
        Q: {
          __factor_family_draft: true,
          __factor_family: {
            factor_family_alias: "LibraryLeaf",
            owner_username: "alice",
            factor_kind: "custom",
            source_code: "class LibraryLeaf: pass",
          },
          parameter_values: {},
        },
      },
    },
  });
  assert.equal(calls.length, 2, "child families must materialize inside-out");
  assert.equal(calls[0].factor_family_alias, "LibraryLeaf");
  assert.equal(calls[1].source_code, "class InlineChild: pass");
  assert.equal(values.P.source_kind, "transient");
  assert.equal(values.P.source_code, "class InlineChild: pass");
  assert.equal(values.P.factor_dependencies.length, 1);
  assert.equal(values.P.factor_dependencies[0].alias, "LibraryLeaf|N:2d");
  const leaf = {
    schema_version: 2, ref: "factor:v2:leaf", owner_ref: "alice",
    alias: "Leaf|N:2", temporary: true, source_kind: "transient",
    source_origin: "test_inline",
    identity: {family_alias: "Leaf", family_formula_fingerprint: "c".repeat(64), params: {N: 2}},
  };
  const middle = {
    ...leaf, ref: "factor:v2:middle", alias: "Middle",
    identity: {family_alias: "Middle", family_formula_fingerprint: "d".repeat(64), params: {P: leaf.ref}},
    factor_dependencies: [leaf],
  };
  const top = {
    ...middle, ref: "factor:v2:top", alias: "Top",
    identity: {family_alias: "Top", family_formula_fingerprint: "e".repeat(64), params: {P: middle.ref}},
    factor_dependencies: [middle, leaf],
  };
  const sourceCalls = [];
  window.FTFactorDetailShared = {
    async loadSourceVersion(_context, value, fingerprint) {
      sourceCalls.push([value.factor_family_alias, fingerprint]);
      return {source_code: "source", family_formula_fingerprint: fingerprint};
    },
  };
  const restored = await window.FTFactorEditor.materializeFamilyDrafts(context, {P: top, Q: leaf});
  assert.equal(sourceCalls.length, 3, "shared descendants must hydrate once per save");
  for (const value of [restored.P, ...restored.P.factor_dependencies,
    ...restored.P.factor_dependencies[0].factor_dependencies, restored.Q]) {
    assert.equal(value.source_kind, "factor_library");
    assert.equal(value.temporary, false);
    assert.equal(value.source_code, undefined, "registered dependencies use the source catalog");
  }
  assert.equal(restored.P.ref, top.ref);
  assert.deepEqual(restored.P.identity, top.identity);
  assert.equal(leaf.source_kind, "transient", "do not mutate the page's original draft");
  window.FTFactorDetailShared.loadSourceVersion = async () => ({
    source_code: "wrong source", family_formula_fingerprint: "f".repeat(64),
  });
  await assert.rejects(() => window.FTFactorEditor.materializeFamilyDrafts(context, {P: leaf}), /源码版本/);
  window.FTFactorDetailShared.loadSourceVersion = async () => { throw new Error("missing source"); };
  await assert.rejects(() => window.FTFactorEditor.materializeFamilyDrafts(context, {P: leaf}), /missing source/);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
