import { objectReferenceLabel } from "./object-reference.ts";
import test from "node:test";
import assert from "node:assert/strict";
import { matchingFamily, objectDetailURL, referenceForField } from "./object-reference.ts";

test("only known identity fields or canonical factor refs become object references", () => {
  assert.deepEqual(referenceForField("owner_ref", "alice"), { kind: "user", ref: "alice" });
  assert.deepEqual(referenceForField("signal", "factor:v2:abc", { owner_username: "alice" }), { kind: "factor", ref: "factor:v2:abc", owner: "alice" });
  assert.equal(referenceForField("owner_ref", "__public_jobs__"), null);
  assert.equal(referenceForField("description", "gold"), null);
  assert.equal(referenceForField("group_ref", "research-group:one"), null);
  assert.equal(referenceForField("product_path_selection_id", "inline:selection"), null);
  assert.equal(referenceForField("authorized_users", "alice")?.kind, "user");
  assert.equal(referenceForField("product_refs", "AU.SHF")?.kind, "product");
  assert.equal(referenceForField("strategy_refs", "strategy:1")?.kind, "strategy");
});

test("profile lookup requires a fully scoped profile key", () => {
  const short = referenceForField("profile_ref", "self", { owner_ref: "alice" })!;
  assert.equal(objectDetailURL(short), null);
  const scoped = referenceForField("profile_ref", "self", { profile_key: "node::alice::self" })!;
  assert.equal(objectDetailURL(scoped), "/api/client/profile-directory/profile?scope=servers&profile_key=node%3A%3Aalice%3A%3Aself");
});

test("family aliases never silently choose another owner's same-named family", () => {
  const rows = [{ family_alias: "Momentum", owner_username: "alice" }, { family_alias: "Momentum", owner_username: "bob" }];
  assert.equal(matchingFamily(rows, "Momentum"), null);
  assert.equal(matchingFamily(rows, "Momentum", "alice"), rows[0]);
  assert.equal(matchingFamily(rows, "Momentum", "carol"), null);
});

test("remote detail URLs escape identities and preserve factor ownership", () => {
  assert.equal(objectDetailURL({ kind: "factor", ref: "factor:v2:a/b", owner: "alice@org" }), "/api/factor-library/factors/detail?factor_ref=factor%3Av2%3Aa%2Fb&owner_username=alice%40org");
  assert.equal(objectDetailURL({ kind: "productGroup", ref: "product-group:a/b" }), "/api/product-library/product-groups/product-group%3Aa%2Fb");
  assert.equal(objectDetailURL({ kind: "user", ref: "alice" }), null);
});


test("the current user's verified display name never replaces their historical object reference", () => {
  const value={kind:"user" as const,ref:"old-principal",label:"old-principal"};
  assert.equal(objectReferenceLabel(value,{username:"old-principal",alias:"Readable name"}),"Readable name");
  assert.equal(value.ref,"old-principal");
  assert.equal(objectReferenceLabel(value,{username:"someone-else",alias:"Readable name"}),"old-principal");
  assert.equal(objectReferenceLabel({...value,label:"Explicit owner label"},{username:"old-principal",alias:"Readable name"}),"Explicit owner label");
  assert.equal(objectReferenceLabel({kind:"profile",ref:"old-principal"},{username:"old-principal",alias:"Readable name"}),"old-principal");
});

test("qualified user references display only the alias for every user", () => {
  const ref = "Org@testB@123456";
  const value = {kind:"user" as const,ref};
  assert.equal(objectReferenceLabel(value,null),"testB");
  assert.equal(objectReferenceLabel({...value,label:ref},{username:"someone-else",alias:"Other"}),"testB");
  assert.equal(objectReferenceLabel({...value,label:"Visible alias"},null),"Visible alias");
  assert.equal(value.ref,ref);
  assert.equal(objectReferenceLabel({kind:"profile",ref},null),ref);
  for (const ref of ["name@example.com","Org@testB@not-an-id","Org@too@many@123"]) {
    assert.equal(objectReferenceLabel({kind:"user",ref},null),ref);
  }
});

test("owner labels use owner metadata and never the containing object's alias", () => {
  assert.deepEqual(referenceForField("owner_ref","Org@testB@123",{alias:"Factor name",owner_alias:"testB"}),
    {kind:"user",ref:"Org@testB@123",label:"testB"});
  assert.deepEqual(referenceForField("owner_ref","Org@testB@123",{alias:"Factor name"}),
    {kind:"user",ref:"Org@testB@123"});
});
