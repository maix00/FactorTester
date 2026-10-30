import assert from "node:assert/strict";
import test from "node:test";
import { keycloakErrorKey, managerRegistrationEnabled } from "./auth-model.ts";

test("organization and server authorization failures retain their specific reason", () => {
  assert.equal(keycloakErrorKey("organization_login_denied"), "organizationLoginDenied");
  assert.equal(keycloakErrorKey("server_organization_unconfigured"), "serverOrganizationUnconfigured");
  assert.equal(keycloakErrorKey("server_organization_conflict"), "serverOrganizationConflict");
  assert.equal(keycloakErrorKey("server_authorization_unavailable"), "serverAuthorizationUnavailable");
  assert.equal(keycloakErrorKey("unrecognized"), "invalid");
  assert.equal(keycloakErrorKey(""), undefined);
});

test("Manager registration is hidden when Keycloak owns account creation", () => {
  assert.equal(managerRegistrationEnabled({
    public_registration_enabled: true,
    authentication_provider: "keycloak",
  }), false);
});

test("Manager registration requires explicit local registration policy", () => {
  assert.equal(managerRegistrationEnabled({
    public_registration_enabled: true,
    authentication_provider: "manager",
  }), true);
  assert.equal(managerRegistrationEnabled({ authentication_provider: "manager" }), false);
  assert.equal(managerRegistrationEnabled(null), false);
});
