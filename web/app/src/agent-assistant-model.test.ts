import assert from "node:assert/strict";
import test from "node:test";
import { agentProfileLabel, agentRuntimeAvailability, isUnboundAgentRuntimeError, selfAgentProfile } from "./agent-assistant-model.ts";

test("self profile resolution requires an explicitly marked self profile", () => {
  assert.equal(selfAgentProfile(null), null);
  assert.equal(selfAgentProfile([{ profile_id: "other", profile_kind: "research" }]), null);
  assert.equal(selfAgentProfile([{ profile_id: "self", profile_kind: "self" }])?.profile_id, "self");
  assert.equal(selfAgentProfile([{ profile_id: "self", is_self_profile: true }])?.profile_id, "self");
  assert.equal(selfAgentProfile([{ profile_id: "", profile_kind: "self" }]), null);
});

test("profile label prefers user-facing alias and title", () => {
  assert.equal(agentProfileLabel({ profile_id: "self", alias: "Desk" }), "Desk");
  assert.equal(agentProfileLabel({ profile_id: "self", title: "Research" }), "Research");
  assert.equal(agentProfileLabel({ profile_id: "self" }), "self");
});

test("assistant runtime availability follows explicit Manager binding metadata", () => {
  assert.equal(agentRuntimeAvailability({ profile_id: "self", runtime: { runtime_kind: "server", configured: true } }), "ready");
  assert.equal(agentRuntimeAvailability({ profile_id: "self", runtime: { runtime_kind: "server", configured: false } }), "unbound");
  assert.equal(agentRuntimeAvailability({ profile_id: "self", runtime: { runtime_kind: "client", configured: true } }), "server-required");
  assert.equal(agentRuntimeAvailability({ profile_id: "self", runtime: { runtime_kind: "server" } }), "unknown");
});

test("unbound runtime errors are recognized without classifying unrelated failures", () => {
  assert.equal(isUnboundAgentRuntimeError("Profile is not bound to a server runtime"), true);
  assert.equal(isUnboundAgentRuntimeError("Profile runtime is not configured"), true);
  assert.equal(isUnboundAgentRuntimeError("Model provider is unavailable"), false);
});
