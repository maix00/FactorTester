import test from "node:test";
import assert from "node:assert/strict";
import {readJobArtifact} from "./artifacts.ts";

test("bounded report reads cancel streams exceeding the limit",async()=>{
 const prior=globalThis.fetch;let cancelled=false;
 globalThis.fetch=async (input)=>String(input).endsWith('/access')?Response.json({access:{url:'https://data.invalid/report',bearer:'test-only'}}):new Response(new ReadableStream({start(controller){controller.enqueue(new Uint8Array(6));},cancel(){cancelled=true;}}));
 try{await assert.rejects(readJobArtifact({job_id:'one'},'report.html',new AbortController().signal,5),/artifact_too_large/);assert.equal(cancelled,true);}finally{globalThis.fetch=prior;}
});

test("bounded report reads retain complete bytes within budget",async()=>{
 const prior=globalThis.fetch;
 globalThis.fetch=async (input)=>String(input).endsWith('/access')?Response.json({access:{url:'https://data.invalid/report',bearer:'test-only'}}):new Response('hello');
 try{assert.equal(await (await readJobArtifact({job_id:'one'},'report.html',new AbortController().signal,5)).text(),'hello');}finally{globalThis.fetch=prior;}
});
