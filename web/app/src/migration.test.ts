import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
test("every old dispatch branch has a uniquely identified migration audit item", () => {
  const inventory = readFileSync(new URL("../MIGRATION.md", import.meta.url), "utf8");
  const routes = readFileSync(new URL("../../../server/manager/web/app/route-dispatch.js", import.meta.url), "utf8");
  const ids = [...inventory.matchAll(/^\| ([A-Z]\d+) \|/gm)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  const mapping = new Map([...inventory.matchAll(/^\| `([^`]+)` \| ([A-Z]\d+) \|/gm)].map((match) => [match[1], match[2]]));
  const kinds = [...routes.matchAll(/case "([^"]+)":/g)].map((match) => match[1]);
  assert.deepEqual([...mapping.keys()].sort(), [...kinds].sort());
  for (const target of mapping.values()) assert.ok(ids.includes(target), target);
});
