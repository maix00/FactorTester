import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Form, Input, Radio, Select, Spin } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { formatDate } from "../format.ts";
import { LocalResearchBridgeError, type LocalResearch, type LocalResearchCapabilities, type LocalResearchClient } from "../local-research-bridge.ts";
import { notify } from "../notifications/core.ts";
import { DetailsCancelButton, DetailsPanel } from "./details-panel.tsx";
import { FunctionPage } from "./function-page.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { TRDataTable } from "./data-table.tsx";
import "./local-research-page.css";

export function ResearchLocationSwitch({value,onChange}:{value:"local"|"server";onChange:(value:"local"|"server")=>void}):React.ReactElement {
  const {t}=useTranslation();
  return <Radio.Group aria-label={t("localResearch.location")} optionType="button" buttonStyle="solid" value={value} onChange={event=>onChange(event.target.value)} options={[
    {value:"local",label:t("localResearch.local")},{value:"server",label:t("localResearch.server")},
  ]} />;
}

function errorMessage(error:unknown,t:(key:string,options?:any)=>string):string {
  const code=error instanceof LocalResearchBridgeError ? error.code : "local_research_bridge_failed";
  return t(`localResearch.errors.${code}`,{defaultValue:t("localResearch.errors.default")});
}

export function LocalResearchPage({client,capabilities,onServer}:{client:LocalResearchClient;capabilities:LocalResearchCapabilities;onServer:()=>void}):React.ReactElement {
  const {t}=useTranslation();
  const [selectedProfile,setSelectedProfile]=useState("");
  const profile=capabilities.profiles.find(value=>value.profile_id===selectedProfile) || capabilities.profiles[0];
  const [rows,setRows]=useState<LocalResearch[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const [offsets,setOffsets]=useState([0]),[page,setPage]=useState(1),[size,setSize]=useState(100),[next,setNext]=useState<number|null>(null),[revision,setRevision]=useState(0);
  const [creating,setCreating]=useState(false),[selected,setSelected]=useState<LocalResearch|null>(null),[profileDetails,setProfileDetails]=useState(false);
  const createAttempt=useRef<{signature:string;id:string}|null>(null);
  const offset=offsets[page-1] ?? 0;
  useEffect(()=>{
    if(!profile)return;
    let active=true;const snapshot=client.snapshot();setLoading(true);setError("");setRows([]);setNext(null);
    void client.list(profile.profile_id,{offset,limit:size}).then(result=>{
      if(active && client.isCurrent(snapshot)){setRows(result.researches);setNext(result.next_offset);}
    }).catch(reason=>{if(active && client.isCurrent(snapshot))setError(errorMessage(reason,t));})
      .finally(()=>{if(active && client.isCurrent(snapshot))setLoading(false);});
    return()=>{active=false;};
  },[client,profile?.profile_id,offset,size,revision,t]);
  if(!profile)return <Alert type="info" message={t("localResearch.noProfiles")} />;
  const chooseProfile=(value:string):void=>{setSelectedProfile(value);setOffsets([0]);setPage(1);setSelected(null);};
  const pagination=(value:number,pageSize:number):void=>{
    if(pageSize!==size){setSize(pageSize);setOffsets([0]);setPage(1);return;}
    if(value===page+1 && next!==null){setOffsets(current=>[...current.slice(0,page),next]);setPage(value);}
    else if(value>=1 && value<page && offsets[value-1]!==undefined)setPage(value);
  };
  const refreshed=():void=>{setOffsets([0]);setPage(1);setRevision(value=>value+1);};
  return <div className="tr-local-research"><FunctionPage title={t("nav.research")} actions={<><ResearchLocationSwitch value="local" onChange={value=>{if(value==="server")onServer();}} />
    {capabilities.actions.includes("create") ? <Button type="primary" onClick={()=>setCreating(true)}>{t("localResearch.create")}</Button>:null}
    <Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={refreshed} /></>}>
    <p className="tr-research-origin">{t("localResearch.privateNote")}</p>
    <p className="tr-research-origin">{t("localResearch.availableFeatures")}</p>
    <div className="tr-library-filters"><div className="tr-reference-select"><Select aria-label={t("research.profile")} value={profile.profile_id} onChange={chooseProfile}
      options={capabilities.profiles.map(value=>({value:value.profile_id,label:value.display_name||value.profile_id}))} /><Button type="link" onClick={()=>setProfileDetails(true)}>{t("details")}</Button></div></div>
    <TRDataTable rows={rows} rowKey="research_id" loading={loading} error={error} pagination={{page,pageSize:size,total:0,mode:"cursor",hasMore:next!==null,onChange:pagination}} columns={[
      {title:t("editor.name"),key:"title",render:(_:unknown,row:LocalResearch)=><button type="button" className="tr-table-link" onClick={()=>setSelected(row)}>{row.title}</button>},
      {title:t("library.description"),dataIndex:"description",render:(value:string)=>value||"—"},
      {title:t("jobs.updated"),dataIndex:"updated_at",render:(value:number)=>formatDate(value,{dateStyle:"medium",timeStyle:"short"})},
    ]} />
    {creating ? <LocalResearchCreate client={client} profiles={capabilities.profiles} initialProfile={profile.profile_id} operation={createAttempt} onClose={()=>setCreating(false)} onCreated={value=>{createAttempt.current=null;setCreating(false);setSelectedProfile(value.profile_id);refreshed();}} />:null}
    {selected ? <LocalResearchDetail client={client} capabilities={capabilities} item={selected} onClose={()=>setSelected(null)} />:null}
    {profileDetails ? <DetailsPanel title={profile.display_name||profile.profile_id} onClose={()=>setProfileDetails(false)} width={520}><PropertyGroups groups={[{key:"profile",title:t("research.profile"),items:[{key:"name",label:t("editor.name"),value:profile.display_name||profile.profile_id},{key:"id",label:t("objectReference.reference"),value:profile.profile_id}]}]} /></DetailsPanel>:null}
  </FunctionPage></div>;
}

function LocalResearchDetail({client,capabilities,item,onClose}:{client:LocalResearchClient;capabilities:LocalResearchCapabilities;item:LocalResearch;onClose:()=>void}):React.ReactElement {
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
  ]}]} /></>:<Spin tip={t("loading")} />}</DetailsPanel>;
}

function LocalResearchCreate({client,profiles,initialProfile,operation,onClose,onCreated}:{client:LocalResearchClient;profiles:LocalResearchCapabilities["profiles"];initialProfile:string;operation:React.MutableRefObject<{signature:string;id:string}|null>;onClose:()=>void;onCreated:(value:LocalResearch)=>void}):React.ReactElement {
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
  return <DetailsPanel title={t("localResearch.create")} onClose={()=>{if(!pending.current)onClose();}} width={600}>
    <p className="tr-research-origin">{t("localResearch.privateNote")}</p>
    {error?<Alert type="error" showIcon message={error}/>:null}
    <Form layout="vertical" initialValues={{profile_id:initialProfile}} disabled={busy} onFinish={save}>
      <Form.Item name="title" label={t("editor.name")} rules={[{required:true,whitespace:true,max:256}]}><Input aria-label={t("editor.name")} autoFocus maxLength={256}/></Form.Item>
      <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{minRows:3,maxRows:8}} maxLength={10000}/></Form.Item>
      <Form.Item name="profile_id" label={t("research.profile")} rules={[{required:true}]}><Select aria-label={t("research.profile")} options={profiles.map(value=>({value:value.profile_id,label:value.display_name||value.profile_id}))}/></Form.Item>
      <div className="tr-inline-actions"><Button type="primary" htmlType="submit" loading={busy}>{t("localResearch.create")}</Button><DetailsCancelButton disabled={busy} closePanel onCancel={onClose}/></div>
    </Form>
  </DetailsPanel>;
}
