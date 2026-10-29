import assert from "node:assert/strict";
import test from "node:test";
import { managerRegistrationEnabled } from "./auth-model.ts";

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
