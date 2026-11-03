import assert from "node:assert/strict";
import test from "node:test";
import { reportExportName, reportExportPayload, reportExportURL, reportResourceURL } from "./report-export.ts";

test("report export selects the addressed channel and escapes report and owner", () => {
  assert.equal(reportExportURL({publication_id:"server:self:r:main",owner_ref:"user/a"},"pdf"),"/api/server-research/self%3Ar%3Amain/export?format=pdf&target_ref=user%2Fa");
  assert.equal(reportExportURL({publication_id:"local:r:main",owner_ref:"other"},"md"),"/api/client/research/r%3Amain/export?format=md");
  assert.equal(reportExportURL({publication_id:"report:1",source_kind:"publication"},"md"),"/api/public-research/report%3A1/export?format=md");
  assert.equal(reportExportURL({profile_ref:"self",report_workspace_id:"r",branch_id:"main"},"pdf"),"/api/server-research/self%3Ar%3Amain/export?format=pdf");
  assert.equal(reportExportURL({publication_id:"server:"},"pdf"),null);
  assert.equal(reportExportURL({},"md"),null);
  assert.equal(reportResourceURL({publication_id:"server:self:r:main",owner_ref:"user/a"},["chapters","chapter:1"]),"/api/server-research/self%3Ar%3Amain/chapters/chapter%3A1?target_ref=user%2Fa");
  assert.equal(reportResourceURL({publication_id:"local:r:main"},["index"]),"/api/client/research/r%3Amain/index");
});

test("desktop bridge uses native format and download name is safe", () => {
  assert.equal(reportExportPayload({publication_id:"local:r:b"},"md").format,"markdown");
  assert.equal(reportExportName("AU/2025:test", "pdf"),"AU-2025-test.pdf");
});

test("CouchDB branches keep their explicit Manager and catalog identity", () => {
  const target = {source_kind:"couchdb", publication_id:`p-${"a".repeat(64)}`, research_id:"research:one", report_id:"report:two", storage_server_id:"internal-manager"};
  const base = `/api/research/research%3Aone/reports/report%3Atwo/couchdb-publication/${target.publication_id}`;
  assert.equal(reportResourceURL(target,["index"]),`${base}?server_id=internal-manager&view=index`);
  assert.equal(reportResourceURL(target,["chapters","chapter/one"]),`${base}?server_id=internal-manager&view=chapter&chapter_id=chapter%2Fone`);
  assert.equal(reportResourceURL(target,["assets","a1"]),`${base}/attachments/research_asset/a1?server_id=internal-manager`);
  assert.equal(reportResourceURL(target,["local-resources","r1"],{inline:"1"}),`${base}/attachments/research_local_resource/r1?inline=1&server_id=internal-manager`);
  assert.equal(reportResourceURL({...target,report_id:""},["index"]),null);
  assert.equal(reportResourceURL({...target,publication_id:"legacy"},["index"]),null);
  assert.equal(reportResourceURL(target,["unknown"]),null);
});
