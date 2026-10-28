import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { readJobArtifact } from "../artifacts.ts";
import type { JobReference } from "../job-model.ts";

/** One authorized artifact, with opaque-origin rendering and transferred bytes. */
export function JobHtmlReport({ job, name }: { job: JobReference; name?: string }): React.ReactElement {
  const { t } = useTranslation();
  const frame=useRef<HTMLIFrameElement>(null);
  const [bytes,setBytes]=useState<ArrayBuffer|null>(null),[ready,setReady]=useState(false);
  const [error,setError]=useState(""),[loading,setLoading]=useState(false),[reload,setReload]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();setBytes(null);setReady(false);setError("");setLoading(Boolean(name));
    if(name)void readJobArtifact(job,name,controller.signal,32*1024*1024).then(blob=>blob.arrayBuffer()).then(buffer=>{
      if(!controller.signal.aborted)setBytes(buffer);
    }).catch(reason=>{if(!controller.signal.aborted){setError(reason.message==="artifact_too_large"?t("jobs.reportTooLarge"):reason.message);setLoading(false);}});
    return ()=>controller.abort();
  },[job.job_id,job.server_id,job.service_port,job.execution_node_id,name,reload]);
  useEffect(()=>{
    if(!ready||!bytes||!frame.current?.contentWindow)return;
    // An opaque sandbox requires '*'; the exact window is the recipient and
    // the receiver accepts messages only from its parent. Transfer, do not copy.
    frame.current.contentWindow.postMessage({type:"tr-artifact-html",bytes,layout:name==="tearsheet.html"?"wide":undefined},"*",[bytes]);
    setBytes(null);setLoading(false);
  },[bytes,ready,name]);
  if(!name)return <Empty description={t("empty")}/>;
  if(error)return <Alert type="error" message={error} action={<Button onClick={()=>{setReady(false);setReload(value=>value+1);}}>{t("retry")}</Button>}/>;
  return <>{loading?<div role="status"><Spin/></div>:null}<iframe key={`${job.server_id}:${job.execution_node_id}:${job.job_id}:${name}:${reload}`} ref={frame}
    className="tr-artifact-frame" title={name} src="/app/artifact-frame" sandbox="allow-scripts allow-downloads"
    onLoad={()=>setReady(true)} style={loading?{visibility:"hidden",height:0}:undefined}/></>;
}
