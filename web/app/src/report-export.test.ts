import assert from "node:assert/strict";
import test from "node:test";
import { reportExportName, reportExportPayload, reportExportURL } from "./report-export.ts";

test("report export selects the addressed channel and escapes report and owner", () => {
  assert.equal(reportExportURL({publication_id:"server:self:r:main",owner_ref:"user/a"},"pdf"),"/api/server-research/self%3Ar%3Amain/export?format=pdf&target_ref=user%2Fa");
  assert.equal(reportExportURL({publication_id:"local:r:main",owner_ref:"other"},"md"),"/api/client/research/r%3Amain/export?format=md");
  assert.equal(reportExportURL({publication_id:"report:1",source_kind:"publication"},"md"),"/api/public-research/report%3A1/export?format=md");
  assert.equal(reportExportURL({profile_ref:"self",report_workspace_id:"r",branch_id:"main"},"pdf"),"/api/server-research/self%3Ar%3Amain/export?format=pdf");
  assert.equal(reportExportURL({publication_id:"server:"},"pdf"),null);
  assert.equal(reportExportURL({},"md"),null);
});

test("desktop bridge uses native format and download name is safe", () => {
  assert.equal(reportExportPayload({publication_id:"local:r:b"},"md").format,"markdown");
  assert.equal(reportExportName("AU/2025:test", "pdf"),"AU-2025-test.pdf");
});
