import assert from "node:assert/strict";
import test from "node:test";
import { AssistantResearchContexts, researchAssistanceSnapshot } from "./assistant-research-context.ts";

test("visible research pages keep independent registrations and most recently interacted context", () => {
  const store = new AssistantResearchContexts();
  const changes: Array<string | null> = [];
  const unsubscribe = store.subscribe(() => changes.push(store.snapshot()?.researchId || null));
  store.set("page-a", {researchId:"research-a",title:"A",section:"details"});
  store.set("page-b", {researchId:"research-b",title:"B",section:"reports"});
  store.activate("page-a");
  assert.equal(store.snapshot()?.researchId,"research-a");
  store.set("page-b", null);
  assert.equal(store.snapshot()?.researchId,"research-a");
  store.set("page-a", {researchId:"research-a",title:"A",section:"evidence"});
  assert.equal(store.snapshot()?.section,"evidence");
  store.set("page-a", null);
  assert.equal(store.snapshot(), null);
  assert.deepEqual(changes,["research-a","research-b","research-a","research-a",null]);
  unsubscribe();
});

test("research assistance publishes only the identity and selected section", () => {
  const payload = researchAssistanceSnapshot({pageId:"panel-a",researchId:"research-a",title:"Private title",section:"reports"});
  assert.deepEqual(payload.document,{schema_version:1,document_kind:"research_context",research_id:"research-a"});
  assert.deepEqual(payload.view,{research_id:"research-a",section:"reports"});
  assert.equal((payload.document_schema as Record<string,unknown>).readOnly,true);
  assert.equal(JSON.stringify(payload).includes("Private title"),false);
});
