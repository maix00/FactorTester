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
export type LocalResearchBinding = { issuer: string; identity_id: string };
export type LocalResearchCapabilities = { binding: LocalResearchBinding; actions: string[]; profiles: LocalResearchProfile[] };
export type LocalResearchCreate = { profile_id: string; title: string; description: string; operation_id: string };
export type LocalResearchPage = { researches: LocalResearch[]; next_offset: number | null };
export type LocalReport = { report_id: string; research_id: string; profile_id: string; title: string; created_at: number };
export type LocalResearchSummary = Omit<LocalResearch, "description">;
export type LocalReportWithResearch = LocalReport & { research: LocalResearchSummary };
export type LocalReportVersion = {generation:number;root_ref:string};
export type LocalReportIndex = { report:LocalReport; chapters:{component_id:string;title:string;preview:string}[]; version:LocalReportVersion };

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
function reportVersion(value:unknown):LocalReportVersion {
  if(!isRecord(value)||!Number.isSafeInteger(value.generation)||(value.generation as number)<0||typeof value.root_ref!=="string"||!/^nodes\/[0-9a-f]{2}\/[0-9a-f]{64}\.json$/.test(value.root_ref)) throw new LocalResearchBridgeError("local_research_invalid_response");
  return {generation:value.generation as number,root_ref:value.root_ref};
}
function binding(value:unknown):LocalResearchBinding {
  if (!isRecord(value)) throw new LocalResearchBridgeError("local_research_invalid_response");
  const issuer=text(value.issuer,2048), identity_id=identifier(value.identity_id);
  try {
    const url=new URL(issuer);
    if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || issuer!==issuer.trim()) throw new Error("invalid issuer");
  } catch { throw new LocalResearchBridgeError("local_research_invalid_response"); }
  return {issuer,identity_id};
}

/** Compare issuer literally except for trailing slashes; stable ID alone is insufficient. */
export function sameLocalResearchBinding(left:LocalResearchBinding,right:LocalResearchBinding):boolean {
  try {
    const a=binding(left), b=binding(right);
    return a.issuer.replace(/\/+$/,"")===b.issuer.replace(/\/+$/,"") && a.identity_id===b.identity_id;
  } catch { return false; }
}
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

function researchSummary(value:unknown):LocalResearchSummary {
  if(!isRecord(value))throw new LocalResearchBridgeError("local_research_invalid_response");
  return {research_id:identifier(value.research_id),profile_id:identifier(value.profile_id),
    title:text(value.title,256),created_at:timestamp(value.created_at),updated_at:timestamp(value.updated_at)};
}

function report(value: unknown): LocalReport {
  if (!isRecord(value)) throw new LocalResearchBridgeError("local_research_invalid_response");
  return {report_id:identifier(value.report_id),research_id:identifier(value.research_id),
    profile_id:identifier(value.profile_id),title:text(value.title,256),created_at:timestamp(value.created_at)};
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
  private profiles: Set<string> | null = null;
  private capabilitySequence = 0;
  private readonly handler: NativeHandler;

  constructor(handler: NativeHandler) { this.handler=handler; }

  /** Invalidation hides late results; it cannot cancel a native write already in progress. */
  invalidate(): void { this.generation += 1; this.actions=null; this.profiles=null; }
  close(): void { this.closed = true; this.invalidate(); }
  /** UI consumers should also check this snapshot immediately before updating state. */
  snapshot(): number { return this.generation; }
  isCurrent(snapshot:number): boolean { return !this.closed && this.generation===snapshot; }

  async capabilities(expected:LocalResearchBinding): Promise<LocalResearchCapabilities> {
    const generation=this.generation;
    const sequence=++this.capabilitySequence;
    this.actions=null;
    this.profiles=null;
    let expectedBinding:LocalResearchBinding;
    try { expectedBinding=binding(expected); }
    catch { throw new LocalResearchBridgeError("local_research_session_unverified"); }
    const reply=await this.call({action:"capabilities"});
    this.requireCurrent(generation);
    if (sequence!==this.capabilitySequence) throw new LocalResearchBridgeError("local_research_capabilities_superseded");
    if (!Array.isArray(reply.actions) || !Array.isArray(reply.profiles)) throw new LocalResearchBridgeError("local_research_invalid_response");
    const current=binding(reply.binding);
    if (!sameLocalResearchBinding(current,expectedBinding)) throw new LocalResearchBridgeError("local_research_session_mismatch");
    const actions=reply.actions.map(value=>text(value,64)), profiles=reply.profiles.map(profile);
    if (new Set(actions).size!==actions.length || new Set(profiles.map(value=>value.profile_id)).size!==profiles.length) throw new LocalResearchBridgeError("local_research_invalid_response");
    this.actions=new Set(actions);
    this.profiles=new Set(profiles.map(value=>value.profile_id));
    return {binding:current,actions,profiles};
  }

  async list(profileId:string, options:{offset?:number;limit?:number} = {}): Promise<LocalResearchPage> {
    this.requireAction("list");
    const profile_id=inputText(profileId,512), offset=options.offset ?? 0, limit=options.limit ?? 100;
    this.requireProfile(profile_id);
    if (!Number.isSafeInteger(offset) || offset<0 || offset>1_000_000 || !Number.isSafeInteger(limit) || limit<1 || limit>200) throw new LocalResearchBridgeError("local_research_invalid_input");
    const generation=this.generation, sequence=this.capabilitySequence;
    const reply=await this.call({action:"list",profile_id,offset,limit});
    this.requireAuthorizedSnapshot(generation,sequence);
    if (!Array.isArray(reply.researches)) throw new LocalResearchBridgeError("local_research_invalid_response");
    const rows=reply.researches.map(research);
    if (rows.length>limit || rows.some(value=>value.profile_id!==profile_id) || new Set(rows.map(value=>value.research_id)).size!==rows.length) throw new LocalResearchBridgeError("local_research_invalid_response");
    const next=reply.next_offset;
    if (next!==null && (!Number.isSafeInteger(next) || next!==offset+rows.length || rows.length===0 || (next as number)>1_000_000)) throw new LocalResearchBridgeError("local_research_invalid_response");
    return {researches:rows,next_offset:next as number|null};
  }

  async listResearches(profileId:string,options:{offset?:number;limit?:number;expectedRevision?:number|null}={}):Promise<LocalResearchPage & {revision:number}> {
    this.requireAction("list_researches");
    const profile_id=inputText(profileId,512),offset=options.offset??0,limit=options.limit??100,expected_revision=options.expectedRevision??null;
    this.requireProfile(profile_id);
    if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000||!Number.isSafeInteger(limit)||limit<1||limit>200||
      (expected_revision!==null&&(!Number.isSafeInteger(expected_revision)||expected_revision<0))||((offset===0)!==(expected_revision===null)))throw new LocalResearchBridgeError("local_research_invalid_input");
    const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"list_researches",profile_id,offset,limit,expected_revision});
    this.requireAuthorizedSnapshot(generation,sequence);
    if(!Array.isArray(reply.researches))throw new LocalResearchBridgeError("local_research_invalid_response");
    const rows=reply.researches.map(research),next=reply.next_offset;
    if(!Number.isSafeInteger(reply.revision)||(reply.revision as number)<0||(expected_revision!==null&&reply.revision!==expected_revision)||rows.length>limit||rows.some(value=>value.profile_id!==profile_id)||new Set(rows.map(value=>value.research_id)).size!==rows.length||
      (next!==null&&(!Number.isSafeInteger(next)||next!==offset+rows.length||rows.length===0||(next as number)>1_000_000)))throw new LocalResearchBridgeError("local_research_invalid_response");
    return {researches:rows,next_offset:next as number|null,revision:reply.revision as number};
  }

  async get(profileId: string, researchId: string): Promise<LocalResearch> {
    this.requireAction("get");
    const profile_id=inputText(profileId,512), research_id=inputText(researchId,512);
    this.requireProfile(profile_id);
    const generation=this.generation, sequence=this.capabilitySequence;
    const reply=await this.call({action:"get",profile_id,research_id});
    this.requireAuthorizedSnapshot(generation,sequence);
    const value=research(reply.research);
    if (value.profile_id!==profile_id || value.research_id!==research_id) throw new LocalResearchBridgeError("local_research_invalid_response");
    return value;
  }

  async listReports(profileId:string,researchId:string,options:{offset?:number;limit?:number}={}):Promise<{reports:LocalReport[];next_offset:number|null}> {
    this.requireAction("list_reports");
    const profile_id=inputText(profileId,512),research_id=inputText(researchId,512),offset=options.offset??0,limit=options.limit??100;
    this.requireProfile(profile_id);
    if (!Number.isSafeInteger(offset)||offset<0||offset>1_000_000||!Number.isSafeInteger(limit)||limit<1||limit>200) throw new LocalResearchBridgeError("local_research_invalid_input");
    const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"list_reports",profile_id,research_id,offset,limit});
    this.requireAuthorizedSnapshot(generation,sequence);
    if (!Array.isArray(reply.reports)) throw new LocalResearchBridgeError("local_research_invalid_response");
    const rows=reply.reports.map(report),next=reply.next_offset;
    if (rows.length>limit||rows.some(value=>value.profile_id!==profile_id||value.research_id!==research_id)||new Set(rows.map(value=>value.report_id)).size!==rows.length||
        (next!==null&&(!Number.isSafeInteger(next)||next!==offset+rows.length||rows.length===0||(next as number)>1_000_000))) throw new LocalResearchBridgeError("local_research_invalid_response");
    return {reports:rows,next_offset:next as number|null};
  }

  async listProfileReports(profileId:string,options:{offset?:number;limit?:number;expectedRevision?:number|null}={}):Promise<{reports:LocalReportWithResearch[];next_offset:number|null;revision:number}> {
    this.requireAction("list_profile_reports");
    const profile_id=inputText(profileId,512),offset=options.offset??0,limit=options.limit??100,expected_revision=options.expectedRevision??null;
    this.requireProfile(profile_id);
    if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000||!Number.isSafeInteger(limit)||limit<1||limit>200||
      (expected_revision!==null&&(!Number.isSafeInteger(expected_revision)||expected_revision<0))||((offset===0)!==(expected_revision===null)))throw new LocalResearchBridgeError("local_research_invalid_input");
    const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"list_profile_reports",profile_id,offset,limit,expected_revision});
    this.requireAuthorizedSnapshot(generation,sequence);
    if(!Array.isArray(reply.reports))throw new LocalResearchBridgeError("local_research_invalid_response");
    const rows=reply.reports.map(value=>{
      if(!isRecord(value))throw new LocalResearchBridgeError("local_research_invalid_response");
      return {...report(value),research:researchSummary(value.research)};
    }),next=reply.next_offset;
    if(!Number.isSafeInteger(reply.revision)||(reply.revision as number)<0||(expected_revision!==null&&reply.revision!==expected_revision)||rows.length>limit||rows.some(value=>value.profile_id!==profile_id||value.research.profile_id!==profile_id||value.research_id!==value.research.research_id)||new Set(rows.map(value=>value.report_id)).size!==rows.length||
      (next!==null&&(!Number.isSafeInteger(next)||next!==offset+rows.length||rows.length===0||(next as number)>1_000_000)))throw new LocalResearchBridgeError("local_research_invalid_response");
    return {reports:rows,next_offset:next as number|null,revision:reply.revision as number};
  }

  async createReport(profileId:string,researchId:string,titleValue:string,operationId:string):Promise<LocalReport> {
    this.requireAction("create_report");
    const profile_id=inputText(profileId,512),research_id=inputText(researchId,512),title=inputText(titleValue,256).trim(),operation_id=inputText(operationId,128);
    this.requireProfile(profile_id);
    const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"create_report",profile_id,research_id,title,operation_id});
    this.requireAuthorizedSnapshot(generation,sequence);
    const value=report(reply.report);
    if(value.profile_id!==profile_id||value.research_id!==research_id||value.title!==title) throw new LocalResearchBridgeError("local_research_invalid_response");
    return value;
  }

  async getReport(profileId:string,researchId:string,reportId:string):Promise<LocalReportIndex> {
    this.requireAction("get_report");
    const profile_id=inputText(profileId,512),research_id=inputText(researchId,512),report_id=inputText(reportId,512);
    this.requireProfile(profile_id);
    const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"get_report",profile_id,research_id,report_id});
    this.requireAuthorizedSnapshot(generation,sequence);
    const value=report(reply.report),index=reply.index;
    if(value.profile_id!==profile_id||value.research_id!==research_id||value.report_id!==report_id||!isRecord(index)||index.report_id!==report_id||!Array.isArray(index.chapters)) throw new LocalResearchBridgeError("local_research_invalid_response");
    const chapters=index.chapters.map(chapter=>{
      if(!isRecord(chapter)) throw new LocalResearchBridgeError("local_research_invalid_response");
      return {component_id:identifier(chapter.component_id),title:text(chapter.title,512,true),preview:text(chapter.preview,512,true)};
    });
    if(new Set(chapters.map(chapter=>chapter.component_id)).size!==chapters.length) throw new LocalResearchBridgeError("local_research_invalid_response");
    return {report:value,chapters,version:reportVersion(reply.version)};
  }

  async getReportChapter(profileId:string,researchId:string,reportId:string,chapterId:string):Promise<{chapter_id:string;components:Record<string,unknown>[],version:LocalReportVersion}> {
    this.requireAction("get_report_chapter");
    const profile_id=inputText(profileId,512),research_id=inputText(researchId,512),report_id=inputText(reportId,512),chapter_id=inputText(chapterId,512);
    this.requireProfile(profile_id);const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"get_report_chapter",profile_id,research_id,report_id,chapter_id});
    this.requireAuthorizedSnapshot(generation,sequence);
    if(!isRecord(reply.chapter)||reply.chapter.chapter_id!==chapter_id||!Array.isArray(reply.chapter.components)||reply.chapter.components.some(item=>!isRecord(item))) throw new LocalResearchBridgeError("local_research_invalid_response");
    return {chapter_id,components:reply.chapter.components as Record<string,unknown>[],version:reportVersion(reply.version)};
  }

  async addReportComponent(input:{profileId:string;researchId:string;reportId:string;componentId:string;kind:"chapter"|"entry";parentId:string;title:string;body:string;version:LocalReportVersion}):Promise<LocalReportVersion> {
    this.requireAction("add_report_component");const profile_id=inputText(input.profileId,512),research_id=inputText(input.researchId,512),report_id=inputText(input.reportId,512);
    this.requireProfile(profile_id);const version=reportVersion(input.version),generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"add_report_component",profile_id,research_id,report_id,component_id:inputText(input.componentId,512),kind:input.kind,parent_id:inputText(input.parentId,512,true),title:inputText(input.title,512,true),body:inputText(input.body,10000,true,true),...version});
    this.requireAuthorizedSnapshot(generation,sequence);return reportVersion(reply.version);
  }

  async publishReport(profileId:string,researchId:string,reportId:string):Promise<{publication_id:string;revision:string;generation:number}> {
    this.requireAction("publish_report");
    const profile_id=inputText(profileId,512),research_id=inputText(researchId,512),report_id=inputText(reportId,512);
    this.requireProfile(profile_id);const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"publish_report",profile_id,research_id,report_id});
    this.requireAuthorizedSnapshot(generation,sequence);
    const value=reply.publication;
    if(!isRecord(value)||value.report_id!==report_id||typeof value.publication_id!=="string"||!/^p-[0-9a-f]{64}$/.test(value.publication_id)||typeof value.revision!=="string"||!value.revision||value.revision.length>256||!Number.isSafeInteger(value.generation)||(value.generation as number)<0) throw new LocalResearchBridgeError("local_research_invalid_response");
    return {publication_id:value.publication_id,revision:value.revision,generation:value.generation as number};
  }

  async pullReport(profileId:string,researchId:string,reportId:string):Promise<{status:"updated"|"up_to_date";local_modified:boolean}> {
    this.requireAction("pull_report");
    const profile_id=inputText(profileId,512),research_id=inputText(researchId,512),report_id=inputText(reportId,512);
    this.requireProfile(profile_id);const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"pull_report",profile_id,research_id,report_id});
    this.requireAuthorizedSnapshot(generation,sequence);
    if((reply.status!=="updated"&&reply.status!=="up_to_date")||typeof reply.local_modified!=="boolean") throw new LocalResearchBridgeError("local_research_invalid_response");
    return {status:reply.status,local_modified:reply.local_modified};
  }

  async syncReports(profileId:string,afterReportId="",limit=4):Promise<{reports:{report_id:string;research_id:string;status:string}[];next_report_id:string|null}> {
    this.requireAction("sync_reports");const profile_id=inputText(profileId,512),after_report_id=inputText(afterReportId,160,true);
    this.requireProfile(profile_id);
    if(!Number.isSafeInteger(limit)||limit<1||limit>16)throw new LocalResearchBridgeError("local_research_invalid_input");
    const generation=this.generation,sequence=this.capabilitySequence;
    const reply=await this.call({action:"sync_reports",profile_id,after_report_id,limit});
    this.requireAuthorizedSnapshot(generation,sequence);
    if(!Array.isArray(reply.reports)||reply.reports.length>limit)throw new LocalResearchBridgeError("local_research_invalid_response");
    const reports=reply.reports.map(value=>{
      if(!isRecord(value)||!["unchanged","updated","published","conflict","denied","unavailable"].includes(String(value.status)))throw new LocalResearchBridgeError("local_research_invalid_response");
      return {report_id:identifier(value.report_id),research_id:identifier(value.research_id),status:String(value.status)};
    });
    if(reports.some((value,index)=>value.report_id <= (index ? reports[index-1].report_id : after_report_id)))throw new LocalResearchBridgeError("local_research_invalid_response");
    const next=reply.next_report_id;
    if(next!==null&&(typeof next!=="string"||!reports.length||next!==reports.at(-1)?.report_id||next<=after_report_id))throw new LocalResearchBridgeError("local_research_invalid_response");
    return {reports,next_report_id:next as string|null};
  }

  /** The caller retains operation_id for retries; this client never retries writes. */
  async create(input: LocalResearchCreate): Promise<LocalResearch> {
    this.requireAction("create");
    const profile_id=inputText(input.profile_id,512), title=inputText(input.title,256).trim();
    this.requireProfile(profile_id);
    const generation=this.generation, sequence=this.capabilitySequence;
    const description=inputText(input.description,10000,true,true), operation_id=inputText(input.operation_id,128);
    const reply=await this.call({action:"create",profile_id,title,description,operation_id});
    this.requireAuthorizedSnapshot(generation,sequence);
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

  private requireProfile(profileId:string):void {
    if (!this.profiles?.has(profileId)) throw new LocalResearchBridgeError("local_research_profile_unavailable");
  }

  private requireAuthorizedSnapshot(generation:number,sequence:number):void {
    this.requireCurrent(generation);
    if (sequence!==this.capabilitySequence || !this.actions || !this.profiles) throw new LocalResearchBridgeError("local_research_capabilities_superseded");
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
