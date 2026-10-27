import assert from "node:assert/strict";
import test from "node:test";
import { newPageInstanceId } from "./page-instance.ts";

test("repeated opens of the same function create distinct DockView identities", () => {
  const ids = Array.from({ length: 100 }, () => newPageInstanceId("configuration"));
  assert.equal(new Set(ids).size, 100);
  assert.ok(ids.every((id) => id.startsWith("tr-configuration-")));
});
