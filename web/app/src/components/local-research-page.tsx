import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Form, Input, Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { formatDate } from "../format.ts";
import { LocalResearchBridgeError, type LocalResearch, type LocalReport, type LocalResearchCapabilities, type LocalResearchClient } from "../local-research-bridge.ts";
import { notify } from "../notifications/core.ts";
import { DetailsCancelButton, DetailsPanel } from "./details-panel.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { TRDataTable } from "./data-table.tsx";

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
    {key:"title",label:t("editor.name"),value:value.title},{key:"description",label:t("library.description"),value:value.description,wide:true},
    {key:"id",label:t("objectReference.reference"),value:value.research_id,wide:true},{key:"updated",label:t("jobs.updated"),value:value.updated_at,render:amount=>formatDate(amount as number,{dateStyle:"medium",timeStyle:"short"})},
  ]}]} />{capabilities.actions.includes("list_reports")&&capabilities.actions.includes("create_report")?<LocalReports client={client} item={value}/>:null}</>:<Spin tip={t("loading")} />}</DetailsPanel>;
}

function LocalReports({client,item}:{client:LocalResearchClient;item:LocalResearch}):React.ReactElement {
  const {t}=useTranslation();
  const [rows,setRows]=useState<LocalReport[]>([]),[page,setPage]=useState(1),[pageSize,setPageSize]=useState(20),[hasMore,setHasMore]=useState(false),[loading,setLoading]=useState(true),[revision,setRevision]=useState(0),[creating,setCreating]=useState(false),[busy,setBusy]=useState(false);
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
  return <section><div className="tr-inline-actions"><h3>{t("researchDetail.reports")}</h3><Button onClick={()=>setCreating(true)} disabled={creating}>{t("researchDetail.create.reports")}</Button></div>
    {creating?<Form layout="inline" onFinish={create}><Form.Item name="title" rules={[{required:true,whitespace:true,max:256}]}><Input aria-label={t("editor.name")} placeholder={t("editor.name")} maxLength={256}/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>{t("researchDetail.create.reports")}</Button><Button disabled={busy} onClick={()=>setCreating(false)}>{t("cancel")}</Button></Form>:null}
    <TRDataTable<LocalReport> rowKey="report_id" rows={rows} loading={loading} columns={[{title:t("editor.name"),dataIndex:"title",key:"title"},{title:t("localResearch.reportCreatedAt"),dataIndex:"created_at",key:"created_at",render:(value:number)=>formatDate(value,{dateStyle:"medium",timeStyle:"short"})}]} pagination={{page,pageSize,total:0,mode:"cursor",hasMore,onChange:(next,size)=>{setPage(next);setPageSize(size);}}}/>
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
