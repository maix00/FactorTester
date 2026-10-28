import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { ReloadOutlined } from "@ant-design/icons";
import { request } from "./api.ts";
import type { ExecutionChoice } from "./plan-document.ts";
import type { ExecutionTarget } from "./execution-target-model.ts";
import "./execution-target.css";

export function ExecutionTargetPicker({ value, onChange, onCapabilities, resolving, error }: {
  value:ExecutionChoice;onChange:(value:ExecutionChoice)=>void;onCapabilities:(types:string[])=>void;resolving:boolean;error:string;
}):React.ReactElement {
  const {t}=useTranslation();
  const [managers,setManagers]=useState<string[]>([]),[targets,setTargets]=useState<ExecutionTarget[]>([]);
  const [reload,setReload]=useState(0),[loading,setLoading]=useState(false),[loadError,setLoadError]=useState("");
  useEffect(()=>{const controller=new AbortController();request("/api/federation/servers",{signal:controller.signal}).then(result=>{
    if(!controller.signal.aborted)setManagers([...new Set([result.server_id,...(result.servers||[]).map((item:any)=>item.server_id)])] as string[]);
  }).catch(reason=>{if(!controller.signal.aborted)setLoadError(reason.message);});return()=>controller.abort();},[]);
  const manager=value.manager_id||managers[0]||"";
  useEffect(()=>{if(!manager)return;const controller=new AbortController();setLoading(true);setTargets([]);
    request(`/api/test-authoring/execution-targets?server_id=${encodeURIComponent(manager)}`,{signal:controller.signal}).then(result=>{if(!controller.signal.aborted){setTargets(result.targets||[]);setLoadError("");}})
      .catch(reason=>{if(!controller.signal.aborted)setLoadError(reason.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});return()=>controller.abort();},[manager,reload]);
  const target=targets.find(row=>JSON.stringify(row.target)===JSON.stringify(value.target)&&row.online);
  const candidates=useMemo(()=>value.mode==="manual"?(target?[target]:[]):targets.filter(row=>row.online),[value.mode,target,targets]);
  const types=useMemo(()=>[...new Set(candidates.flatMap(row=>row.target.test_types))].sort(),[candidates]);
  useEffect(()=>onCapabilities(types),[types,onCapabilities]);
  const bundles=useMemo(()=>[...new Map(candidates.flatMap(row=>row.offers).map(offer=>{
    const owner=String((offer.installation as any).owner||"platform"),bundle_id=offer.installation.bundle_id;
    return [JSON.stringify([bundle_id,owner]),{bundle_id,owner}];})).values()],[candidates]);
  const update=(patch:Partial<ExecutionChoice>):void=>{const next={...value,...patch,manager_id:patch.manager_id||manager};delete next.resolved;delete next.resolved_ref;onChange(next);};
  const binding = !resolving && !error ? value.resolved : undefined;
  const resolved=binding?.target;
  const resolvedBundles=[...new Set((binding?.inputs||[]).map((input:any)=>{
    const install=input.offer.installation;return `${install.bundle_id} · ${install.bundle_version} · ${install.node_id}`;
  }))] as string[];
  return <section className="tr-execution-target" aria-label={t("executionTopology.title")}>
    <div className="tr-execution-heading"><h2>{t("executionTopology.title")}</h2><Button type="text" icon={<ReloadOutlined/>} loading={loading} aria-label={t("executionTopology.refresh")} onClick={()=>setReload(n=>n+1)}/></div>
    <label className="tr-execution-row"><span>{t("executionTopology.mode")}</span><Select value={value.mode} options={[{value:"auto",label:t("executionTopology.auto")},{value:"manual",label:t("executionTopology.manual")}]} onChange={mode=>update({mode,target:undefined})}/></label>
    <label className="tr-execution-row"><span>Manager</span><Select value={manager||undefined} options={managers.map(id=>({value:id,label:id}))} onChange={manager_id=>update({manager_id,target:undefined,bundles:[]})}/></label>
    {value.mode==="manual"?<label className="tr-execution-row"><span>{t("executionTopology.service")}</span><Select value={target?.route_id} loading={loading} options={targets.map(row=>({value:row.route_id,label:`${row.target.node_id} · ${row.target.service_id}`,disabled:!row.online}))} onChange={id=>update({target:targets.find(row=>row.route_id===id)?.target,bundles:[]})}/></label>:null}
    <label className="tr-execution-row"><span>Bundle</span><Select mode="multiple" showSearch optionFilterProp="label" value={value.bundles.map(bundle=>JSON.stringify([bundle.bundle_id,bundle.owner]))} options={bundles.map(bundle=>({value:JSON.stringify([bundle.bundle_id,bundle.owner]),label:`${bundle.bundle_id} · ${bundle.owner}`}))} onChange={keys=>update({bundles:keys.map(key=>{const [bundle_id,owner]=JSON.parse(key);return {bundle_id,owner};})})}/></label>
    {value.mode==="auto"?<div className="tr-execution-resolved" aria-busy={resolving}>
      <label className="tr-execution-row"><span>{t("executionTopology.service")}</span><Select disabled value={resolved?`${resolved.manager_id} → ${resolved.node_id} · ${resolved.service_id}`:undefined} placeholder={t("executionTopology.pending")}/></label>
      <label className="tr-execution-row"><span>{t("executionTopology.installations")}</span><Select mode="multiple" disabled value={resolvedBundles}/></label>
      {resolving?<div className="tr-execution-resolving" role="status"><Spin size="small"/>{t("executionTopology.resolving")}</div>:null}
    </div>:null}
    {error||loadError?<Alert type="error" showIcon message={error||loadError}/>:null}
  </section>;
}
