import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Form, Input, Popconfirm, Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { formatDate } from "../format.ts";
import { LocalResearchBridgeError, type LocalResearch, type LocalReport, type LocalReportIndex, type LocalResearchCapabilities, type LocalResearchClient } from "../local-research-bridge.ts";
import { notify } from "../notifications/core.ts";
import { DetailsCancelButton, DetailsPanel } from "./details-panel.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { TRDataTable } from "./data-table.tsx";
import { ReportEditor } from "./report-editor.tsx";

function errorMessage(error:unknown,t:(key:string,options?:any)=>string):string {
  const code=error instanceof LocalResearchBridgeError ? error.code : "local_research_bridge_failed";
  return t(`localResearch.errors.${code}`,{defaultValue:t("localResearch.errors.default")});
}

export function LocalResearchDetail({client,capabilities,item,onClose}:{client:LocalResearchClient;capabilities:LocalResearchCapabilities;item:LocalResearch;onClose:()=>void}):React.ReactElement {
  const {t}=useTranslation();const [value,setValue]=useState<LocalResearch|null>(capabilities.actions.includes("get")?null:item),[error,setError]=useState("");
  useEffect(()=>{
    if(!capabilities.actions.includes("get"))return;
    let active=true;const snapshot=client.snapshot();
    void client.get(item.profile_id,item.research_id).then(row=>{if(active&&client.isCurrent(snapshot))setValue(row);}).catch(reason=>{if(active&&client.isCurrent(snapshot))setError(errorMessage(reason,t));});
    return()=>{active=false;};
  },[client,item.profile_id,item.research_id,t]);
  return <DetailsPanel title={item.title} onClose={onClose} width={680}>{error?<Alert type="error" showIcon message={error}/>:value?<><p className="tr-research-origin">{t("localResearch.privateNote")}</p><PropertyGroups groups={[{key:"research",title:t("details"),items:[
    {key:"title",label:t("editor.name"),value:value.title},...(value.description ? [{key:"description",label:t("library.description"),value:value.description,wide:true}] : []),
    {key:"id",label:t("objectReference.reference"),value:value.research_id,wide:true},{key:"updated",label:t("jobs.updated"),value:value.updated_at,render:amount=>formatDate(amount as number,{dateStyle:"medium",timeStyle:"short"})},
  ]}]} />{capabilities.actions.includes("list_reports")&&capabilities.actions.includes("create_report")?<LocalReports client={client} item={value} canOpen={capabilities.actions.includes("get_report")} canEdit={capabilities.actions.includes("get_report_chapter")&&capabilities.actions.includes("add_report_component")} canPublish={capabilities.actions.includes("publish_report")} canPull={capabilities.actions.includes("pull_report")}/>:null}</>:<Spin tip={t("loading")} />}</DetailsPanel>;
}

function LocalReports({client,item,canOpen,canEdit,canPublish,canPull}:{client:LocalResearchClient;item:LocalResearch;canOpen:boolean;canEdit:boolean;canPublish:boolean;canPull:boolean}):React.ReactElement {
  const {t}=useTranslation();
  const [rows,setRows]=useState<LocalReport[]>([]),[page,setPage]=useState(1),[pageSize,setPageSize]=useState(20),[hasMore,setHasMore]=useState(false),[loading,setLoading]=useState(true),[revision,setRevision]=useState(0),[creating,setCreating]=useState(false),[busy,setBusy]=useState(false);
  const [selected,setSelected]=useState<LocalReport|null>(null),[index,setIndex]=useState<LocalReportIndex|null>(null);
  const [publishing,setPublishing]=useState(false);
  const [pullRevision,setPullRevision]=useState(0);
  const publicationPending=useRef(false);
  const operation=useRef<{title:string;id:string}|null>(null),pending=useRef(false),mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{
    let active=true;const snapshot=client.snapshot();setLoading(true);
    void client.listReports(item.profile_id,item.research_id,{offset:(page-1)*pageSize,limit:pageSize}).then(result=>{
      if(active&&client.isCurrent(snapshot)){setRows(result.reports);setHasMore(result.next_offset!==null);}
    }).catch(reason=>{if(active&&client.isCurrent(snapshot))notify({code:"research.local.reports.load",type:"error",message:errorMessage(reason,t)});})
      .finally(()=>{if(active&&client.isCurrent(snapshot))setLoading(false);});
    return()=>{active=false;};
  },[client,item.profile_id,item.research_id,page,pageSize,revision,t]);
  useEffect(()=>{
    if(!selected)return;
    let active=true;const snapshot=client.snapshot();setIndex(null);
    void client.getReport(item.profile_id,item.research_id,selected.report_id).then(value=>{if(active&&client.isCurrent(snapshot))setIndex(value);})
      .catch(reason=>{if(active&&client.isCurrent(snapshot)){setSelected(null);notify({code:"research.local.report.load",type:"error",message:errorMessage(reason,t)});}});
    return()=>{active=false;};
  },[client,item.profile_id,item.research_id,selected,revision,t]);
  const requester=useMemo(()=>{
    if(!selected)return undefined;
    const base=`/api/research-reports/${encodeURIComponent(selected.report_id)}`;
    let inFlight:Promise<LocalReportIndex>|null=null;
    const current=()=>{if(!inFlight){const next=client.getReport(item.profile_id,item.research_id,selected.report_id);inFlight=next;void next.finally(()=>{if(inFlight===next)inFlight=null;}).catch(()=>undefined);}return inFlight;};
    return async(url:string,options:RequestInit={})=>{
      if(options.signal?.aborted)throw new DOMException("Aborted","AbortError");
      if(url===`${base}/attachments`)return {attachments:[]};
      if(url===base||url===`${base}/agent`){
        const value=await current();
        if(url===base)return {document:{_rev:JSON.stringify(value.version),projection_hash:"local"},access:{can_write:true}};
        return {manifest:{chapters:value.chapters.map(chapter=>({chapter_id:chapter.component_id,title:chapter.title}))}};
      }
      if(url.startsWith(`${base}/chapters/`)){
        const chapter=await client.getReportChapter(item.profile_id,item.research_id,selected.report_id,decodeURIComponent(url.slice(`${base}/chapters/`.length)));
        return {chapter:{chapter_id:chapter.chapter_id,components:chapter.components}};
      }
      if(url===`${base}/operations`&&typeof options.body==="string"){
        const payload=JSON.parse(options.body),operation=payload.operation,version=JSON.parse(payload.base_rev);
        const chapter=operation.op==="insert_chapter",component=chapter ? {component_id:operation.chapter_id,title:operation.title,body:""} : operation.component;
        if(!chapter&&operation.op!=="insert_component")throw new Error("Unsupported report operation");
        try{return await client.addReportComponent({profileId:item.profile_id,researchId:item.research_id,reportId:selected.report_id,componentId:component.component_id,kind:chapter?"chapter":"entry",parentId:chapter?"":operation.parent_id,title:component.title||"",body:component.body||"",version});}
        catch(reason){if(reason instanceof LocalResearchBridgeError&&reason.code==="local_report_version_conflict")throw Object.assign(reason,{status:409});throw reason;}
      }
      throw new Error("Unsupported local report request");
    };
  },[client,item.profile_id,item.research_id,selected]);
  const create=async({title}:{title:string})=>{
    if(pending.current)return;
    title=title.trim();if(!operation.current||operation.current.title!==title)operation.current={title,id:crypto.randomUUID()};
    const snapshot=client.snapshot();pending.current=true;setBusy(true);
    try{
      await client.createReport(item.profile_id,item.research_id,title,operation.current.id);
      if(mounted.current&&client.isCurrent(snapshot)){operation.current=null;setCreating(false);setPage(1);setRevision(value=>value+1);notify({code:"research.local.report.created",type:"success",message:t("researchDetail.notices.report")});}
    }catch(reason){if(mounted.current&&client.isCurrent(snapshot))notify({code:"research.local.report.create",type:"error",message:`${t("localResearch.writeUnconfirmed")} ${errorMessage(reason,t)}`});}
    finally{pending.current=false;if(mounted.current&&client.isCurrent(snapshot))setBusy(false);}
  };
  const publish=async()=>{
    if(!selected||publicationPending.current)return;
    const snapshot=client.snapshot();publicationPending.current=true;setPublishing(true);
    try{await client.publishReport(item.profile_id,item.research_id,selected.report_id);if(mounted.current&&client.isCurrent(snapshot))notify({code:"research.local.report.published",type:"success",message:t("localResearch.published")});}
    catch(reason){if(mounted.current&&client.isCurrent(snapshot)){const code=reason instanceof LocalResearchBridgeError?reason.code:"";notify({code:"research.local.report.publish",type:"error",message:code==="local_report_publication_conflict"?t("report.revisionConflict"):code==="local_report_publication_denied"?t("localResearch.publicationDenied"):t("localResearch.publicationFailed")});}}
    finally{publicationPending.current=false;if(mounted.current&&client.isCurrent(snapshot))setPublishing(false);}
  };
  const pull=async()=>{
    if(!selected||publicationPending.current)return;
    const snapshot=client.snapshot();publicationPending.current=true;setPublishing(true);
    try{const value=await client.pullReport(item.profile_id,item.research_id,selected.report_id);if(mounted.current&&client.isCurrent(snapshot)){if(value.status==="updated"){setPullRevision(v=>v+1);setRevision(v=>v+1);}notify({code:"research.local.report.pulled",type:value.local_modified?"warning":"success",message:value.local_modified?t("localResearch.localChanges"):t("localResearch.pulled")});}}
    catch(reason){if(mounted.current&&client.isCurrent(snapshot)){const code=reason instanceof LocalResearchBridgeError?reason.code:"";notify({code:"research.local.report.pull",type:"error",message:code==="local_report_sync_conflict"?t("localResearch.syncConflict"):code==="local_report_publication_denied"?t("localResearch.publicationDenied"):t("localResearch.pullFailed")});}}
    finally{publicationPending.current=false;if(mounted.current&&client.isCurrent(snapshot))setPublishing(false);}
  };
  if(selected)return <section><div className="tr-inline-actions"><Button aria-label={t("back")} disabled={publishing} onClick={()=>setSelected(null)}>{t("back")}</Button><h3>{selected.title}</h3>{canPublish?<Popconfirm title={t("localResearch.publishConfirm")} okText={t("localResearch.publish")} cancelText={t("cancel")} onConfirm={()=>void publish()}><Button loading={publishing}>{t("localResearch.publish")}</Button></Popconfirm>:null}{canPull?<Popconfirm title={t("localResearch.pullConfirm")} okText={t("localResearch.pull")} cancelText={t("cancel")} onConfirm={()=>void pull()}><Button disabled={publishing}>{t("localResearch.pull")}</Button></Popconfirm>:null}</div>{index ? index.chapters.length ? <ul>{index.chapters.map(chapter=><li key={chapter.component_id}>{chapter.title}</li>)}</ul> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("empty")} /> : <Spin tip={t("loading")} />}{canEdit&&requester?<ReportEditor key={`${selected.report_id}:${pullRevision}`} publicationID={selected.report_id} requester={requester} appendOnly onUpdated={()=>setRevision(value=>value+1)} />:null}</section>;
  return <section><div className="tr-inline-actions"><h3>{t("researchDetail.reports")}</h3><Button onClick={()=>setCreating(true)} disabled={creating}>{t("researchDetail.create.reports")}</Button></div>
    {creating?<Form layout="inline" onFinish={create}><Form.Item name="title" rules={[{required:true,whitespace:true,max:256}]}><Input aria-label={t("editor.name")} placeholder={t("editor.name")} maxLength={256}/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>{t("researchDetail.create.reports")}</Button><Button disabled={busy} onClick={()=>setCreating(false)}>{t("cancel")}</Button></Form>:null}
    <TRDataTable<LocalReport> rowKey="report_id" rows={rows} loading={loading} columns={[{title:t("editor.name"),dataIndex:"title",key:"title",render:(title:string,row:LocalReport)=>canOpen?<button type="button" className="tr-table-link" onClick={()=>setSelected(row)}>{title}</button>:title},{title:t("localResearch.reportCreatedAt"),dataIndex:"created_at",key:"created_at",render:(value:number)=>formatDate(value,{dateStyle:"medium",timeStyle:"short"})}]} pagination={{page,pageSize,total:0,mode:"cursor",hasMore,onChange:(next,size)=>{setPage(next);setPageSize(size);}}}/>
  </section>;
}

export function LocalResearchCreate({client,profiles,initialProfile,operation,onClose,onCreated}:{client:LocalResearchClient;profiles:LocalResearchCapabilities["profiles"];initialProfile:string;operation:React.MutableRefObject<{signature:string;id:string}|null>;onClose:()=>void;onCreated:(value:LocalResearch)=>void}):React.ReactElement {
  const {t}=useTranslation();const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const active=useRef(true),pending=useRef(false);
  useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
  const save=async(values:{profile_id:string;title:string;description?:string}):Promise<void>=>{
    if(pending.current)return;
    const title=values.title.trim(),description=values.description||"",profile_id=values.profile_id;
    const signature=JSON.stringify([profile_id,title,description]);
    if(!operation.current || operation.current.signature!==signature)operation.current={signature,id:crypto.randomUUID()};
    const snapshot=client.snapshot();pending.current=true;setBusy(true);setError("");
    try{
      const value=await client.create({profile_id,title,description,operation_id:operation.current.id});
      if(active.current&&client.isCurrent(snapshot)){notify({code:"research.local.created",type:"success",message:t("localResearch.created")});onCreated(value);}
    }catch(reason){if(active.current&&client.isCurrent(snapshot))setError(`${t("localResearch.writeUnconfirmed")} ${errorMessage(reason,t)}`);}
    finally{pending.current=false;if(active.current&&client.isCurrent(snapshot))setBusy(false);}
  };
  return <DetailsPanel title={t("research.create")} onClose={()=>{if(!pending.current)onClose();}} width={600}>
    {error?<Alert type="error" showIcon message={error}/>:null}
    <Form layout="vertical" initialValues={{profile_id:initialProfile}} disabled={busy} onFinish={save}>
      <Form.Item name="title" label={t("editor.name")} rules={[{required:true,whitespace:true,max:256}]}><Input aria-label={t("editor.name")} autoFocus maxLength={256}/></Form.Item>
      <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{minRows:3,maxRows:8}} maxLength={10000}/></Form.Item>
      <Form.Item name="profile_id" label={profiles.length>1 ? t("research.profile") : undefined} hidden={profiles.length===1} rules={[{required:true}]}><Select aria-label={t("research.profile")} options={profiles.map(value=>({value:value.profile_id,label:value.display_name||value.profile_id}))}/></Form.Item>
      <div className="tr-inline-actions"><Button type="primary" htmlType="submit" loading={busy}>{t("research.create")}</Button><DetailsCancelButton disabled={busy} closePanel onCancel={onClose}/></div>
    </Form>
  </DetailsPanel>;
}
