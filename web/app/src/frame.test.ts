import assert from "node:assert/strict";
import test from "node:test";
import { pageFrameSrc } from "./frame-url.ts";

test("page frames keep the shell route and add exactly one presentation query", () => {
  assert.equal(pageFrameSrc("/jobs?section=types"), "/jobs?section=types&presentation=embedded");
  assert.equal(pageFrameSrc("/backtest"), "/backtest?presentation=embedded");
  assert.equal(pageFrameSrc("/research?section=researches", true), "/research?section=researches&presentation=canvas");
});
