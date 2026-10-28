import assert from "node:assert/strict";
import test from "node:test";
import { JobFeed } from "./job-feed.ts";
test("server feed follows opaque cursors and does not claim an unavailable page", async () => {
  const seen: URL[] = [], feed = new JobFeed(), signal = new AbortController().signal;
  const reader = async (path: string) => { const url = new URL(path, "http://fixture"); seen.push(url); const second = url.searchParams.get("cursor") === "cursor:2"; return { jobs: [{ job_id: second ? "b" : "a" }], has_more: !second, next_cursor: second ? undefined : "cursor:2" }; };
  const value = await feed.read(reader, { scope: "server", page: 8, size: 20, signal });
  assert.equal(value.page, 2); assert.equal(value.jobs?.[0].job_id, "b"); assert.equal(seen.length, 2);
  seen.length = 0; await feed.read(reader, { scope: "server", page: 2, size: 20, signal });
  assert.equal(seen.length, 1); assert.equal(seen[0].searchParams.get("cursor"), "cursor:2");
});
test("private scopes preserve account selection without inheriting a server cursor", async () => {
  let target = ""; const signal = new AbortController().signal;
  await new JobFeed().read(async (path) => { target = path; return { jobs: [] }; }, { scope: "subordinates", username: "child user", page: 3, size: 50, signal });
  const url = new URL(target, "http://fixture"); assert.equal(url.searchParams.get("username"), "child user"); assert.equal(url.searchParams.get("page"), "3"); assert.equal(url.searchParams.has("cursor"), false);
});
test("aborted cursor reads cannot advance the feed", async () => {
  const controller = new AbortController(); let calls = 0;
  await assert.rejects(() => new JobFeed().read(async () => { calls += 1; controller.abort(); return { has_more: true, next_cursor: "x" }; }, { scope: "server", page: 2, size: 20, signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls, 1);
});
