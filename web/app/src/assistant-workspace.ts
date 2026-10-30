import { AssistantContextPublisher, type AssistanceStatus } from "./assistant-context-publisher.ts";
import type { AssistantResearchContext } from "./assistant-research-context.ts";

type Request = (url:string, options?:RequestInit) => Promise<any>;

export async function createAssistantWorkspace(request:Request, profileID:string):Promise<string> {
  const value = await request("/api/client/profile-agent/assistance/workspaces", {
    method:"POST",body:JSON.stringify({profile_id:profileID}),
  });
  const id = typeof value.workspace_id === "string" ? value.workspace_id.trim() : "";
  if (!id) throw new Error("Assistant workspace was not issued");
  return id;
}

function isExpired(cause:unknown):boolean {
  return !!cause && typeof cause === "object" && (cause as {code?:unknown}).code === "assistance_workspace_expired";
}

/** Own one server-issued workspace and bind every Agent turn to it. */
export class AssistantWorkspaceSession {
  private requestAPI:Request;
  private profileID:string;
  private workspaceID:string;
  private publisher!:AssistantContextPublisher;
  private desired:AssistantResearchContext | null = null;
  private onStatus:(status:AssistanceStatus) => void;
  private renewal:Promise<void> | null = null;
  private closed = false;

  private constructor(request:Request, profileID:string, workspaceID:string, onStatus:(status:AssistanceStatus) => void) {
    this.requestAPI=request; this.profileID=profileID; this.workspaceID=workspaceID; this.onStatus=onStatus;
    this.attach(workspaceID);
  }

  static async open(request:Request, profileID:string, onStatus:(status:AssistanceStatus) => void = () => undefined):Promise<AssistantWorkspaceSession> {
    return new AssistantWorkspaceSession(request,profileID,await createAssistantWorkspace(request,profileID),onStatus);
  }

  set(context:AssistantResearchContext | null):void {
    if (this.closed) return;
    this.desired=context;
    this.publisher.set(context);
  }

  async ready():Promise<void> {
    if (this.closed) throw new Error("Assistant workspace is closed");
    const publisher=this.publisher, id=this.workspaceID;
    try {await publisher.ready();}
    catch (cause) {
      if (!isExpired(cause)) throw cause;
      await this.renew(id);
    }
    if (publisher !== this.publisher && this.workspaceID !== id) await this.publisher.ready();
  }

  request:Request = async (url,options) => {
    if (url !== "/api/client/profile-agent/rpc" || options?.method !== "POST" || typeof options.body !== "string") return this.requestAPI(url,options);
    if (this.closed) throw new Error("Assistant workspace is closed");
    const body = JSON.parse(options.body);
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("Invalid Agent RPC request");
    const turn = body.method === "turn/start" || body.method === "turn/steer";
    if (turn) await this.ready();
    const send = (id:string):Promise<any> => this.requestAPI(url,{...options,body:JSON.stringify({...body,workspace_id:id})});
    const id = this.workspaceID;
    try {return await send(id);}
    catch (cause) {
      if (!isExpired(cause)) throw cause;
      // The Manager rejects an expired workspace before dispatching the RPC.
      await this.renew(id);
      if (turn) await this.ready();
      return send(this.workspaceID);
    }
  };

  async close():Promise<void> {
    if (this.closed) return;
    this.closed=true; this.desired=null;
    try {await this.publisher.close();}
    finally {await this.release(this.workspaceID).catch(cause => {if (!isExpired(cause)) throw cause;});}
  }

  private attach(id:string):void {
    let publisher:AssistantContextPublisher;
    publisher = new AssistantContextPublisher(this.requestAPI,this.profileID,id,status => {
      if (!this.closed && this.publisher === publisher) this.onStatus(status);
    });
    this.publisher=publisher;
    publisher.set(this.desired);
  }

  private async release(id:string):Promise<void> {
    const query=new URLSearchParams({profile_id:this.profileID,workspace_id:id});
    await this.requestAPI(`/api/client/profile-agent/assistance/workspaces?${query}`,{method:"DELETE",keepalive:true});
  }

  private async renew(expiredID:string):Promise<void> {
    if (this.closed) throw new Error("Assistant workspace is closed");
    if (this.workspaceID !== expiredID) return;
    if (!this.renewal) {
      this.renewal=(async () => {
        const next=await createAssistantWorkspace(this.requestAPI,this.profileID);
        if (this.closed) {await this.release(next).catch(() => undefined);throw new Error("Assistant workspace is closed");}
        const previous=this.publisher;
        this.workspaceID=next;this.attach(next);
        void previous.close().catch(() => undefined);
      })().finally(() => {this.renewal=null;});
    }
    await this.renewal;
  }
}
