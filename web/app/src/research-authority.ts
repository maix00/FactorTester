import { request } from "./configuration/api.ts";

export type ResearchAuthority = { authority: "legacy" | "keycloak"; create_research?: boolean };

/** Old servers predate this endpoint; do not infer Keycloak authority from a login. */
export async function researchAuthority(signal: AbortSignal, invalid: string): Promise<ResearchAuthority> {
  let value;
  try { value = await request("/api/research/capabilities/keycloak-sharing", {signal,cache:"no-store"}); }
  catch (reason) {
    if ((reason as {status?:number}).status === 404) return {authority:"legacy"};
    throw reason;
  }
  const capabilities=value.capabilities;
  if (!capabilities || capabilities.schema !== "tr-research-keycloak-sharing-v1" || !["legacy","keycloak"].includes(capabilities.authority)) throw new Error(invalid);
  return capabilities as ResearchAuthority;
}
