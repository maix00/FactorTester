import { researchAssistanceSnapshot, type AssistantResearchContext } from "./assistant-research-context.ts";

type Request = (url:string, options?:RequestInit) => Promise<any>;
export type AssistanceStatus = "idle" | "syncing" | "ready" | "unavailable";

function sameContext(a:AssistantResearchContext | null, b:AssistantResearchContext | null):boolean {
  return a === b || !!a && !!b && a.pageId === b.pageId && a.researchId === b.researchId && a.section === b.section;
}

/** Serialize updates so an old response cannot restore the previous page. */
export class AssistantContextPublisher {
  private desired:AssistantResearchContext | null = null;
  private published:AssistantResearchContext | null = null;
  private possiblyPublished = new Set<string>();
  private generation = 0;
  private completed = 0;
  private clientRevision = 0;
  private pending:Promise<void> | null = null;
  private failure:unknown = null;
  private closed = false;
  private request:Request;
  private profileID:string;
  private workspaceID:string;
  private onStatus:(status:AssistanceStatus) => void;

  constructor(request:Request, profileID:string, workspaceID:string,
              onStatus:(status:AssistanceStatus) => void = () => undefined) {
    this.request = request; this.profileID = profileID; this.workspaceID = workspaceID; this.onStatus = onStatus;
  }

  set(context:AssistantResearchContext | null):void {
    if (this.closed || sameContext(this.desired,context)) return;
    this.desired = context;
    this.generation++;
    this.start();
  }

  /** A turn must use an acknowledged, freshly authorized page. */
  async ready():Promise<void> {
    if (this.closed) throw new Error("Assistant workspace is closed");
    if (this.desired || this.failure) { this.generation++; this.start(); }
    await this.wait();
  }

  async close():Promise<void> {
    if (!this.closed) {this.closed = true;this.desired = null;this.generation++;this.start();}
    await this.wait();
  }

  private start():void {
    if (this.pending) return;
    this.pending = this.drain().finally(() => {
      this.pending = null;
      if (this.completed !== this.generation) this.start();
    });
  }

  private async wait():Promise<void> {
    while (this.pending) await this.pending;
    if (this.failure) throw this.failure;
  }

  private async remove(pageID:string):Promise<void> {
    const query = new URLSearchParams({profile_id:this.profileID,workspace_id:this.workspaceID,tab_id:pageID,client_revision:String(++this.clientRevision)});
    await this.request(`/api/client/profile-agent/assistance/page?${query}`,{method:"DELETE",keepalive:true});
  }

  private async drain():Promise<void> {
    while (this.completed !== this.generation) {
      const generation = this.generation, target = this.desired;
      this.onStatus("syncing");
      try {
        if (target) {
          // A timed-out request may still have been accepted by the server.
          this.possiblyPublished.add(target.pageId);
          const result = await this.request("/api/client/profile-agent/assistance/publish", {
            method:"POST",body:JSON.stringify({profile_id:this.profileID,workspace_id:this.workspaceID,tab_id:target.pageId,
              workspace:{client_revision:++this.clientRevision,active_tab_id:target.pageId,tabs:[{
                tab_id:target.pageId,kind:"research",research_id:target.researchId,assistance:researchAssistanceSnapshot(target),
              }]} }),
          });
          if (result.page?.tab_id !== target.pageId || result.page?.assistance?.document?.research_id !== target.researchId) {
            this.published = null;
            throw new Error("Research context is not authorized");
          }
          this.published = target;
          this.possiblyPublished.clear();
          this.possiblyPublished.add(target.pageId);
        } else {
          for (const pageID of this.possiblyPublished) {
            await this.remove(pageID);
            this.possiblyPublished.delete(pageID);
          }
          this.published = null;
        }
        this.failure = null;
      } catch (cause) {
        this.failure = cause;
        // The request may have reached the server even when its response was
        // lost. Try to remove both the old and attempted page before a turn.
        for (const pageID of this.possiblyPublished) {
          try { await this.remove(pageID); this.possiblyPublished.delete(pageID); if (this.published?.pageId === pageID) this.published = null; }
          catch { /* The next attempt remains blocked until the error is resolved. */ }
        }
        if (!target && !this.possiblyPublished.size) this.failure = null;
      }
      this.completed = generation;
      if (generation === this.generation) this.onStatus(this.failure ? "unavailable" : target ? "ready" : "idle");
    }
  }
}
