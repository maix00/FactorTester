/**
 * The native host owns authentication, Profile access and durable storage.
 * Detecting a WebKit handler is not itself an authorization decision.
 */
export const LOCAL_RESEARCH_BRIDGE_SCHEMA = "tr-local-research-bridge:v1";

export type LocalResearchProfile = { profile_id: string; display_name: string };
export type LocalResearch = {
  research_id: string;
  profile_id: string;
  title: string;
  description: string;
  created_at: number;
  updated_at: number;
};
export type LocalResearchCapabilities = { actions: string[]; profiles: LocalResearchProfile[] };
export type LocalResearchCreate = { profile_id: string; title: string; description: string; operation_id: string };

type NativeHandler = { postMessage: (message: Record<string, unknown>) => unknown };
type NativeHost = { webkit?: { messageHandlers?: { tradeResearchLocalResearch?: unknown } } };

export class LocalResearchBridgeError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.name = "LocalResearchBridgeError"; this.code=code; }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, maximum: number, allowEmpty = false, multiline = false): string {
  const controls = multiline ? /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/ : /[\u0000-\u001f\u007f]/;
  if (typeof value !== "string" || value.length > maximum || controls.test(value) || (!allowEmpty && !value.trim())) {
    throw new LocalResearchBridgeError("local_research_invalid_response");
  }
  return value;
}

function identifier(value: unknown): string { return text(value, 512); }
function timestamp(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new LocalResearchBridgeError("local_research_invalid_response");
  return value;
}

function profile(value: unknown): LocalResearchProfile {
  if (!isRecord(value)) throw new LocalResearchBridgeError("local_research_invalid_response");
  return {profile_id:identifier(value.profile_id),display_name:text(value.display_name,512,true)};
}

function research(value: unknown): LocalResearch {
  if (!isRecord(value)) throw new LocalResearchBridgeError("local_research_invalid_response");
  return {
    research_id:identifier(value.research_id),profile_id:identifier(value.profile_id),
    title:text(value.title,256),description:text(value.description,10000,true,true),
    created_at:timestamp(value.created_at),updated_at:timestamp(value.updated_at),
  };
}

function inputText(value: unknown, maximum: number, allowEmpty = false, multiline = false): string {
  try { return text(value,maximum,allowEmpty,multiline); }
  catch { throw new LocalResearchBridgeError("local_research_invalid_input"); }
}

/**
 * Returns null in browsers or older desktop clients. The caller must still
 * negotiate capabilities; each request is independently checked by Swift.
 */
export function localResearchBridge(host: unknown): LocalResearchClient | null {
  if (!isRecord(host)) return null;
  const handler = (host as NativeHost).webkit?.messageHandlers?.tradeResearchLocalResearch;
  if (!isRecord(handler) || typeof handler.postMessage !== "function") return null;
  return new LocalResearchClient(handler as NativeHandler);
}

export class LocalResearchClient {
  private generation = 0;
  private closed = false;
  private actions: Set<string> | null = null;
  private capabilitySequence = 0;
  private readonly handler: NativeHandler;

  constructor(handler: NativeHandler) { this.handler=handler; }

  /** Invalidation hides late results; it cannot cancel a native write already in progress. */
  invalidate(): void { this.generation += 1; this.actions=null; }
  close(): void { this.closed = true; this.invalidate(); }
  /** UI consumers should also check this snapshot immediately before updating state. */
  snapshot(): number { return this.generation; }
  isCurrent(snapshot:number): boolean { return !this.closed && this.generation===snapshot; }

  async capabilities(): Promise<LocalResearchCapabilities> {
    const generation=this.generation;
    const sequence=++this.capabilitySequence;
    this.actions=null;
    const reply=await this.call({action:"capabilities"});
    this.requireCurrent(generation);
    if (sequence!==this.capabilitySequence) throw new LocalResearchBridgeError("local_research_capabilities_superseded");
    if (!Array.isArray(reply.actions) || !Array.isArray(reply.profiles)) throw new LocalResearchBridgeError("local_research_invalid_response");
    const actions=reply.actions.map(value=>text(value,64)), profiles=reply.profiles.map(profile);
    if (new Set(actions).size!==actions.length || new Set(profiles.map(value=>value.profile_id)).size!==profiles.length) throw new LocalResearchBridgeError("local_research_invalid_response");
    this.actions=new Set(actions);
    return {actions,profiles};
  }

  async list(): Promise<LocalResearch[]> {
    this.requireAction("list");
    const generation=this.generation;
    const reply=await this.call({action:"list"});
    this.requireCurrent(generation);
    if (!Array.isArray(reply.researches)) throw new LocalResearchBridgeError("local_research_invalid_response");
    const rows=reply.researches.map(research);
    if (new Set(rows.map(value=>JSON.stringify([value.profile_id,value.research_id]))).size!==rows.length) throw new LocalResearchBridgeError("local_research_invalid_response");
    return rows;
  }

  async get(profileId: string, researchId: string): Promise<LocalResearch> {
    this.requireAction("get");
    const generation=this.generation;
    const profile_id=inputText(profileId,512), research_id=inputText(researchId,512);
    const reply=await this.call({action:"get",profile_id,research_id});
    this.requireCurrent(generation);
    const value=research(reply.research);
    if (value.profile_id!==profile_id || value.research_id!==research_id) throw new LocalResearchBridgeError("local_research_invalid_response");
    return value;
  }

  /** The caller retains operation_id for retries; this client never retries writes. */
  async create(input: LocalResearchCreate): Promise<LocalResearch> {
    this.requireAction("create");
    const generation=this.generation;
    const profile_id=inputText(input.profile_id,512), title=inputText(input.title,256).trim();
    const description=inputText(input.description,10000,true,true), operation_id=inputText(input.operation_id,128);
    const reply=await this.call({action:"create",profile_id,title,description,operation_id});
    this.requireCurrent(generation);
    const value=research(reply.research);
    if (value.profile_id!==profile_id || value.title!==title || value.description!==description) throw new LocalResearchBridgeError("local_research_invalid_response");
    return value;
  }

  private requireAction(action:string):void {
    if (this.closed) throw new LocalResearchBridgeError("local_research_client_closed");
    if (!this.actions?.has(action)) throw new LocalResearchBridgeError("local_research_capability_unavailable");
  }

  private requireCurrent(generation:number):void {
    if (!this.isCurrent(generation)) throw new LocalResearchBridgeError("local_research_session_changed");
  }

  private async call(message: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (this.closed) throw new LocalResearchBridgeError("local_research_client_closed");
    const generation=this.generation;
    let result:unknown;
    try { result=await this.handler.postMessage(message); }
    catch {
      if (generation!==this.generation || this.closed) throw new LocalResearchBridgeError("local_research_session_changed");
      throw new LocalResearchBridgeError("local_research_bridge_failed");
    }
    if (generation!==this.generation || this.closed) throw new LocalResearchBridgeError("local_research_session_changed");
    if (!isRecord(result)) throw new LocalResearchBridgeError("local_research_invalid_response");
    if (result.success===false) {
      const code=typeof result.code==="string" && /^[a-z][a-z0-9_]{0,63}$/.test(result.code) ? result.code : "local_research_bridge_failed";
      throw new LocalResearchBridgeError(code);
    }
    if (result.success!==true || result.schema!==LOCAL_RESEARCH_BRIDGE_SCHEMA) throw new LocalResearchBridgeError("local_research_invalid_response");
    return result;
  }
}
