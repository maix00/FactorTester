/** The registry's enabled bit is not a Keycloak authorization decision. */
export function deviceAuthorizationState(device: Record<string, unknown>, scope: "self" | "admin"):
  "active" | "revoked" | "authorizationDenied" | "authorizationUnknown" {
  if (device.enabled !== true) return "revoked";
  if (scope !== "self" || typeof device.keycloak_authorized !== "boolean") return "authorizationUnknown";
  return device.keycloak_authorized ? "active" : "authorizationDenied";
}
