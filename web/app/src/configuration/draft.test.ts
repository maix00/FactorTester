import assert from "node:assert/strict";
import test from "node:test";
import { acknowledgeSave, createDraft, parseDraft, readPath, writePath } from "./draft.ts";

test("invalid JSON is retained and cannot be silently replaced by form edits", () => {
  const text = '{"analyses":';
  assert.ok(parseDraft(text).error);
  assert.throws(() => writePath(text, ["analyses", "backtest"], {}));
});

test("adding one setting preserves unknown extension fields and zero/false/null", () => {
  const original = { extension: { foreign: [0, false, null] }, analyses: {} };
  const text = writePath(JSON.stringify(original), ["analyses", "backtest", "execution", "settings", "split_count"], 5);
  const value = parseDraft(text).value!;
  assert.deepEqual(value.extension, original.extension);
  assert.equal(readPath(value, ["analyses", "backtest", "execution", "settings", "split_count"]), 5);
  assert.throws(() => writePath(text, ["__proto__", "polluted"], true));
});

test("save acknowledgment advances revision but preserves concurrent typing", () => {
  const draft = createDraft({ count: 1 }, 7);
  const changed = { ...draft, text: '{"count":2}' };
  const saved = acknowledgeSave(changed, draft.text, { count: 1 }, 8);
  assert.equal(saved.text, changed.text);
  assert.equal(saved.revision, 8);
  assert.notEqual(saved.text, saved.savedText);
  assert.deepEqual(parseDraft(acknowledgeSave(draft, draft.text, { count: 1 }, 8).text).value, { count: 1 });
});
