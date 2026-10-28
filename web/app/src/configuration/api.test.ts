import assert from "node:assert/strict";
import test from "node:test";
import { request } from "./api.ts";

test("authoring requests retain same-origin authentication and reject explicit failure envelopes", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => {
      assert.equal(options?.credentials, "same-origin");
      return new Response(JSON.stringify({ success: false, error: "Rejected" }), { status: 200 });
    };
    await assert.rejects(request("/api/test"), /Rejected/);
    globalThis.fetch = async () => new Response(JSON.stringify({ success: true, revision: 8 }));
    assert.deepEqual(await request("/api/test"), { success: true, revision: 8 });
  } finally { globalThis.fetch = original; }
});
