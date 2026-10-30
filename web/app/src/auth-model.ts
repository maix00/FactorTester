export type AuthenticationEntry = {
  public_registration_enabled?: boolean;
  authentication_provider?: "manager" | "keycloak";
};

export function managerRegistrationEnabled(entry: AuthenticationEntry | null): boolean {
  return Boolean(
    entry?.public_registration_enabled
    && entry.authentication_provider !== "keycloak",
  );
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
