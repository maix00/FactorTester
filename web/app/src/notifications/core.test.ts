import assert from "node:assert/strict";
import test from "node:test";
import { bindNotificationSink, notify, pendingNoticeCount, resetNotifications } from "./core.ts";

test("notification queue dedupes codes and limits visible messages", () => {
  resetNotifications();
  const shown: string[] = [];
  const closers: Array<() => void> = [];
  bindNotificationSink((notice, done) => {
    shown.push(notice.key);
    closers.push(done);
  });
  notify({ code: "jobs.load_failed", type: "error", message: "failed" });
  notify({ code: "jobs.load_failed", type: "error", message: "failed" });
  for (const code of ["a", "b", "c", "d"]) {
    notify({ code, message: code });
  }
  assert.deepEqual(shown, ["jobs.load_failed", "a", "b"]);
  assert.equal(pendingNoticeCount(), 5);
  closers[0]();
  assert.deepEqual(shown, ["jobs.load_failed", "a", "b", "c"]);
  assert.equal(pendingNoticeCount(), 4);
});
