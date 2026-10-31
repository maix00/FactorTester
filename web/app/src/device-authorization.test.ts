import assert from "node:assert/strict";
import { test } from "node:test";
import { deviceAuthorizationState } from "./device-authorization.ts";

test("an enabled registry row is only active after an actual Keycloak decision", () => {
  assert.equal(deviceAuthorizationState({ enabled: true, keycloak_authorized: true }, "self"), "active");
  assert.equal(deviceAuthorizationState({ enabled: true, keycloak_authorized: false }, "self"), "authorizationDenied");
  assert.equal(deviceAuthorizationState({ enabled: true }, "self"), "authorizationUnknown");
  assert.equal(deviceAuthorizationState({ enabled: true, keycloak_authorized: true }, "admin"), "authorizationUnknown");
  assert.equal(deviceAuthorizationState({ enabled: false, keycloak_authorized: true }, "self"), "revoked");
});

test("each device authorization state has Chinese and English labels", async () => {
  (globalThis as any).localStorage = { getItem: () => null, setItem: () => undefined };
  (globalThis as any).document = { documentElement: { lang: "" } };
  const { resources } = await import("./i18n.ts");
  for (const language of ["zh", "en"] as const) {
    for (const state of ["active", "revoked", "authorizationDenied", "authorizationUnknown"] as const) {
      assert.ok(resources[language].common.devices[state]);
    }
  }
});
