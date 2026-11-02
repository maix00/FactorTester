import assert from "node:assert/strict";
import test from "node:test";
import { reportReference } from "./report-references.ts";

test("report links preserve declared identities and reject malformed addresses", () => {
  assert.deepEqual(reportReference("factortester://product/Product%2FFutures%2F_products%2FAU.SHF"), {kind:"product",ref:"Product/Futures/_products/AU.SHF"});
  assert.deepEqual(reportReference("traderesearch://factor-family/family%3Av2%3A123"), {kind:"factor_family",ref:"family:v2:123"});
  assert.deepEqual(reportReference("factortester-local://abcdef0123456789abcdef01"), {kind:"local_resource",ref:"abcdef0123456789abcdef01"});
  for (const invalid of ["javascript:alert(1)","https://example.com", "factortester://factor/x?other=1", "factortester://u:p@factor/x", "factortester://factor/%ZZ", "factortester-local://not-an-id"]) assert.equal(reportReference(invalid), null);
});
