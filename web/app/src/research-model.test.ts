import assert from "node:assert/strict";
import test from "node:test";
import { linkedResearchID, reportBranches, reportRowID, researchRowID, selectReportBranch, researchRelationCandidates, mergeResearchDirectory, researchDirectoryRowKey } from "./research-model.ts";

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

test("profile candidates distinguish identical names owned by different users", () => {
  const rows = [{principal_ref:"alice",profile_id:"self"},{principal_ref:"bob",profile_id:"self"}];
  assert.deepEqual(researchRelationCandidates("profile", rows, {members:[{principal_ref:"alice",profile_ref:"self"}]}, "alice"), [rows[1]]);
});


test("one user retains all Profile copies when a research also exists on Manager", () => {
  const local = ["self", "lab", "review"].map(profile_id => ({research_id:"r",owner_ref:"alice",profile_id,__local:true}));
  const result = mergeResearchDirectory([{research_id:"r",owner_ref:"alice",title:"Shared"}],local,"alice");
  assert.equal(result.length,3);
  assert.deepEqual(result.map(row=>row.profile_id),["self","lab","review"]);
  assert.ok(result.every(row=>row.__hasLocal && !row.__local));
  assert.equal(new Set(result.map(row=>researchDirectoryRowKey(row))).size,3);
  assert.equal(new Set(local.map(row=>researchDirectoryRowKey(row))).size,3);
  assert.equal(new Set(result.map(row=>row.owner_ref)).size,1);
});

test("Profile-specific Manager rows never consume another Profile or another user's local copy", () => {
  const local=[{research_id:"r",owner_ref:"alice",profile_id:"lab",__local:true},
    {research_id:"r",owner_ref:"alice",profile_id:"review",__local:true},
    {research_id:"r",owner_ref:"bob",profile_id:"lab",__local:true}];
  const result=mergeResearchDirectory([{research_id:"r",owner_ref:"alice",profile_ref:"lab"}],local,"alice");
  assert.equal(result.length,3);
  assert.ok(result.some(row=>row.owner_ref==="bob"&&row.__local));
  assert.ok(result.some(row=>row.profile_id==="review"&&row.__local));
  assert.equal(result.filter(row=>row.__hasLocal).length,1);
  const reports=local.map(row=>({...row,report_id:"same-report"}));
  assert.equal(new Set(reports.map(row=>researchDirectoryRowKey(row,true))).size,3);
});
