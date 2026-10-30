import assert from "node:assert/strict";
import test from "node:test";
import { linkedResearchID, reportBranches, reportRowID, researchRowID, selectReportBranch } from "./research-model.ts";

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
