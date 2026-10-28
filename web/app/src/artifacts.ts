import { request } from "./configuration/api.ts";
import { jobURL, type JobReference } from "./job-model.ts";
/** Manager issues a scoped grant; bytes come from its existing data plane. */
export async function readJobArtifact(job: JobReference, name: string, signal: AbortSignal, maxBytes?:number): Promise<Blob> {
  const issued = await request(jobURL(job, `/artifacts/${encodeURIComponent(name)}/access`), { method: "POST", headers: { "Idempotency-Key": `artifact-read:${crypto.randomUUID()}` }, signal });
  const access = issued.access;
  if (!access?.url || !access.bearer) throw new Error("Invalid artifact access grant");
  const response = await fetch(access.url, { credentials: "omit", redirect: "error", headers: { Authorization: `Bearer ${access.bearer}` }, signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  if(maxBytes===undefined)return response.blob();
  if(Number(response.headers.get("Content-Length"))>maxBytes){await response.body?.cancel();throw new Error("artifact_too_large");}
  if(!response.body)throw new Error("Empty artifact response");
  const reader=response.body.getReader();const chunks:Uint8Array<ArrayBuffer>[]=[];let size=0;
  try{
    while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;
      if(size>maxBytes){await reader.cancel();throw new Error("artifact_too_large");}chunks.push(value);}
    return new Blob(chunks,{type:response.headers.get("Content-Type")||"text/html"});
  }finally{reader.releaseLock();}
}
