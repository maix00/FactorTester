import assert from "node:assert/strict";
import test from "node:test";
import { linkedResearchID, reportBranches, reportRowID, researchRowID, selectReportBranch, researchRelationCandidates } from "./research-model.ts";

test("research workspace routes keep the research identity", () => {
  assert.equal(researchRowID({ research_id: "research:v1:one", report_id: "report-one" }), "research:v1:one");
});

test("report list identity and readable version identity stay distinct", () => {
  const row = {
    research_id: "research:v1:one",
    report_id: "report-one",
    branches: [
      { publication_id: "publication-old", branch_ref: "old", source_kind: "publication" },
      { publication_id: "publication-current", branch_ref: "main", source_kind: "publication", selected: true },
    ],
  };
  assert.equal(reportRowID(row), "report-one");
  assert.equal(selectReportBranch(row)?.publication_id, "publication-current");
  assert.equal(selectReportBranch(row, "publication-old")?.publication_id, "publication-old");
  assert.equal(reportRowID({ source_ref: "local:report-one" }), "local:report-one");
});

test("a research or catalog report id is never treated as a readable publication", () => {
  const row = { research_id: "research:v1:one", report_id: "report-one", branches: [] };
  assert.deepEqual(reportBranches(row), []);
  assert.equal(selectReportBranch(row), undefined);
});

test("unpublished reports link to their Research identity, never their report id", () => {
  assert.equal(linkedResearchID({ report_id: "report-one", research_id: "research:v1:one" }), "research:v1:one");
  assert.equal(linkedResearchID({ report_id: "report-one" }), "");
});

test("research relation choices exclude bound profiles and active workspaces without conflating owners", () => {
  const profiles = [{profile_id:"self"},{profile_id:"other"},{profile_id:""}];
  assert.deepEqual(researchRelationCandidates("profile", profiles, {members:[{profile_ref:"profile:self"}]}, "alice"), [profiles[1]]);
  const members = [{principal_ref:"alice",profile_ref:"p"},{principal_ref:"bob",profile_ref:"p"},{principal_ref:"bob",profile_ref:"q",status:"removed"}];
  assert.deepEqual(researchRelationCandidates("workspace", members, {workspaces:[{principal_ref:"alice",profile_ref:"p",status:"active"}]}, ""), [members[1]]);
  assert.deepEqual(researchRelationCandidates("report", members, {}, ""), [members[0],members[1]]);
});
