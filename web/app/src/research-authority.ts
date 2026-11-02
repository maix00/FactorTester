import { request } from "./configuration/api.ts";

export type ResearchAuthority = { authority: "keycloak"; create_research?: boolean };

/** Research creation is available only when the Manager reports Keycloak authority. */
export async function researchAuthority(signal: AbortSignal, invalid: string): Promise<ResearchAuthority> {
  const value = await request("/api/research/capabilities/keycloak-sharing", {signal,cache:"no-store"});
  const capabilities=value.capabilities;
  if (!capabilities || capabilities.schema !== "tr-research-keycloak-sharing-v1" || capabilities.authority !== "keycloak") throw new Error(invalid);
  return capabilities as ResearchAuthority;
}
