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
