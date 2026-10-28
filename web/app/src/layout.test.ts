import assert from "node:assert/strict";
import test from "node:test";
import { createMemoryLayoutStore, restoreLayout, serializeLayout, workspaceLayoutKey } from "./layout.ts";

test("layout serialization stores only ids, group and order", () => {
  const raw = serializeLayout({ version: 1, pages: [
    { id: "a", pageId: "jobs", groupId: "main", order: 1, result: { secret: true } } as never,
    { id: "b", pageId: "research", groupId: "main", order: 0 },
  ] });
  assert.deepEqual(JSON.parse(raw), { version: 1, pages: [
    { pageId: "research", groupId: "main", order: 0 },
    { pageId: "jobs", groupId: "main", order: 1 },
  ] });
});

test("invalid layout restores null; memory store round-trips", () => {
  assert.equal(restoreLayout("{bad"), null);
  const store = createMemoryLayoutStore();
  store.save({ version: 1, pages: [{ id: "a", pageId: "jobs", groupId: "main", order: 0 }] });
  assert.equal(store.load()?.pages[0].pageId, "jobs");
});

test("workspace references are isolated between signed-in principals",()=>{
 assert.notEqual(workspaceLayoutKey("alice"),workspaceLayoutKey("bob"));
 assert.equal(workspaceLayoutKey("alice"),workspaceLayoutKey("alice"));
});
