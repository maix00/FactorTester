import assert from "node:assert/strict";
import test from "node:test";
import { evidenceFile } from "./research-evidence-download.ts";

test("evidence file download uses the scoped capability and checks size", async () => {
  const original = globalThis.fetch; const calls: {url:string; init?:RequestInit}[] = [];
  globalThis.fetch = async (input, init) => {
    calls.push({url:String(input),init});
    if (calls.length === 1) return Response.json({success:true,access:{url:"https://node.example/file",bearer:"test-capability",expected_size:3},object:{filename:"file.txt"}});
    return new Response("abc");
  };
  try {
    const result = await evidenceFile("evidence:test", "source:test");
    assert.equal(await result.blob.text(),"abc"); assert.equal(result.filename,"file.txt");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)),{object_kind:"evidence_file",evidence_ref:"evidence:test",source_ref:"source:test"});
    assert.equal(calls[1].init?.credentials,"omit"); assert.equal(calls[1].init?.redirect,"error");
    assert.equal((calls[1].init?.headers as Record<string,string>).Authorization,"Bearer test-capability");
  } finally { globalThis.fetch = original; }
});

test("truncated and unauthorized evidence files are rejected", async () => {
  const original = globalThis.fetch; let count = 0;
  globalThis.fetch = async () => ++count === 1 ? Response.json({access:{url:"https://node.example/file",bearer:"test",expected_size:10}}) : new Response("abc");
  try { await assert.rejects(() => evidenceFile("evidence:test","source:test"),/evidence_size_mismatch/); }
  finally { globalThis.fetch = original; }
  globalThis.fetch = async () => Response.json({success:false,error:"forbidden"},{status:403});
  try { await assert.rejects(() => evidenceFile("evidence:test","source:test"),/forbidden/); }
  finally { globalThis.fetch = original; }
});
