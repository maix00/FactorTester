export type AgentProfile = {
  profile_id: string;
  profile_key?: string;
  alias?: string;
  title?: string;
  profile_kind?: string;
  is_self_profile?: boolean;
  runtime?: { runtime_kind?: string; configured?: boolean };
  active_claim?: Record<string, unknown>;
};

export type AgentRuntimeAvailability = "ready" | "server-required" | "unbound" | "unknown";
export type AgentAssistantSetupStep = "ready" | "bind-server" | "claim-agent" | "client-runtime";

export function agentRuntimeAvailability(profile: AgentProfile): AgentRuntimeAvailability {
  if (profile.runtime?.runtime_kind === "client") return "server-required";
  if (profile.runtime?.runtime_kind !== "server") return "unknown";
  if (profile.runtime.configured === false) return "unbound";
  if (profile.runtime.configured === true) return "ready";
  return "unknown";
}

export function agentAssistantSetupStep(profile: AgentProfile): AgentAssistantSetupStep {
  const availability = agentRuntimeAvailability(profile);
  if (availability === "server-required") return "client-runtime";
  if (availability !== "ready") return "bind-server";
  return profile.active_claim ? "ready" : "claim-agent";
}

export function isUnboundAgentRuntimeError(message: string): boolean {
  const normalized = message.trim().toLocaleLowerCase();
  return normalized.includes("not bound") || normalized.includes("not configured");
}

export function selfAgentProfile(value: unknown): AgentProfile | null {
  if (!Array.isArray(value)) return null;
  const profile = value.find((item) => item && typeof item === "object" &&
    ((item as AgentProfile).is_self_profile === true || (item as AgentProfile).profile_kind === "self"));
  if (!profile || typeof (profile as AgentProfile).profile_id !== "string" || !(profile as AgentProfile).profile_id.trim()) return null;
  return profile as AgentProfile;
}

export function agentProfileLabel(profile: AgentProfile): string {
  return String(profile.alias || profile.title || profile.profile_id);
}
