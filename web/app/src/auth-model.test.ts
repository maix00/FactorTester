import assert from "node:assert/strict";
import test from "node:test";
import { keycloakErrorKey, keycloakLoginAvailable } from "./auth-model.ts";

test("organization and server authorization failures retain their specific reason", () => {
  assert.equal(keycloakErrorKey("organization_login_denied"), "organizationLoginDenied");
  assert.equal(keycloakErrorKey("server_organization_unconfigured"), "serverOrganizationUnconfigured");
  assert.equal(keycloakErrorKey("server_organization_conflict"), "serverOrganizationConflict");
  assert.equal(keycloakErrorKey("server_authorization_unavailable"), "serverAuthorizationUnavailable");
  assert.equal(keycloakErrorKey("unrecognized"), "invalid");
  assert.equal(keycloakErrorKey(""), undefined);
});

test("only an explicit Keycloak provider enables sign-in", () => {
  assert.equal(keycloakLoginAvailable({authentication_provider:"keycloak"}),true);
  for(const entry of [null,{}, {authentication_provider:"manager"}, {authentication_provider:"unknown"}]) {
    assert.equal(keycloakLoginAvailable(entry),false);
  }
});
