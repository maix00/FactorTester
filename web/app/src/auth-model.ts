/** The application never falls back to local account/password authentication. */
export function keycloakLoginAvailable(entry: {authentication_provider?: string} | null): boolean {
  return entry?.authentication_provider === "keycloak";
}

/** Map only known OIDC outcomes to user-facing translations. */
export function keycloakErrorKey(error: string): string | undefined {
  if (!error) return undefined;
  const keys: Record<string, string> = {
    provider: "provider", unverified: "unverified", public_login_denied: "publicLoginDenied", device: "deviceRejected",
    organization_login_denied: "organizationLoginDenied", server_organization_unconfigured: "serverOrganizationUnconfigured",
    server_organization_conflict: "serverOrganizationConflict", server_authorization_unavailable: "serverAuthorizationUnavailable",
  };
  return keys[error] || "invalid";
}
