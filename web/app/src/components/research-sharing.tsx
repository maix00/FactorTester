import React, { useEffect, useRef, useState } from "react";
import { Alert, AutoComplete, Button, Checkbox, Form, Input, Popconfirm, Select, Spin, Tabs, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { formatDate } from "../format.ts";
import { notify } from "../notifications/core.ts";
import { ObjectReference } from "./object-reference.tsx";
import { objectReferenceLabel } from "../object-reference.ts";
import { TRDataTable } from "./data-table.tsx";
import "./research-sharing.css";

type Target = { researchId: string; reportId?: string };
type Capabilities = { can_manage_grants: boolean; can_manage_links: boolean };
type Grant = { identity_id: string; username: string; enabled: boolean; scopes: string[] };
type ShareLink = { link_id: string; target_kind: string; report_id?: string; mode: string; expires_at?: number; revoked_at?: number; redeemed_by?: string; created_at?: number };
type Status = { loading: boolean; error: string; unavailable: "" | "missing" | "disabled"; capabilities: Capabilities | null };

function targetParams(target: Target): URLSearchParams {
  return new URLSearchParams({target_kind:target.reportId ? "report" : "research", report_id:target.reportId || ""});
}

/** All mutations use explicitly Keycloak-only endpoints; the capability response is only a UI hint. */
export function ResearchSharing({ target }: { target: Target }): React.ReactElement {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>({loading:true,error:"",unavailable:"",capabilities:null});
  const [retry, setRetry] = useState(0), [tab, setTab] = useState("grants");
  const base = `/api/research/${encodeURIComponent(target.researchId)}`;
  const params = targetParams(target).toString();
  useEffect(() => {
    const controller = new AbortController();
    setStatus({loading:true,error:"",unavailable:"",capabilities:null});
    void request(`${base}/keycloak-sharing-capabilities?${params}`, {signal:controller.signal,cache:"no-store"}).then(value => {
      if (controller.signal.aborted) return;
      const c = value.capabilities;
      if (!c || c.schema !== "tr-research-keycloak-target-sharing-v1" || c.authority !== "keycloak" ||
          c.research_id !== target.researchId || c.report_id !== (target.reportId || "") ||
          c.target_kind !== (target.reportId ? "report" : "research") ||
          typeof c.can_manage_grants !== "boolean" || typeof c.can_manage_links !== "boolean") throw new Error(t("researchDetail.invalidResponse"));
      setStatus({loading:false,error:"",unavailable:"",capabilities:c});
      setTab(c.can_manage_grants ? "grants" : "links");
    }).catch(reason => {
      if (!controller.signal.aborted) setStatus({loading:false,error:String(reason.message || reason),unavailable:reason.status === 404 ? "missing" : reason.code === "keycloak_sharing_unavailable" ? "disabled" : "",capabilities:null});
    });
    return () => controller.abort();
  }, [base, params, retry, t]);
  if (status.loading) return <Spin tip={t("loading")} />;
  if (status.error) return <Alert type={status.unavailable ? "info" : "error"} showIcon
    message={t(status.unavailable === "missing" ? "researchSharing.targetUnavailable" : status.unavailable === "disabled" ? "researchSharing.unavailable" : "researchSharing.capabilityError")}
    description={status.unavailable ? undefined : status.error} action={<Button onClick={() => setRetry(value => value + 1)}>{t("retry")}</Button>} />;
  const capabilities = status.capabilities;
  if (!capabilities?.can_manage_grants && !capabilities?.can_manage_links) return <Alert type="info" showIcon message={t("researchSharing.noAccess")} />;
  return <><Tabs activeKey={tab} onChange={setTab} items={[
    ...(capabilities.can_manage_grants ? [{key:"grants",label:t("researchSharing.users"),children:<ResearchGrants target={target} />}]:[]),
    ...(capabilities.can_manage_links ? [{key:"links",label:t("researchSharing.links"),children:<ResearchLinks target={target} />}]:[]),
  ]} /></>;
}

function ResearchGrants({target}:{target:Target}):React.ReactElement {
  const {t}=useTranslation();
  const base=`/api/research/${encodeURIComponent(target.researchId)}/keycloak-grants`, query=targetParams(target).toString();
  const [grants,setGrants]=useState<Grant[]>([]), [error,setError]=useState(""), [loading,setLoading]=useState(true), [revision,setRevision]=useState(0);
  const [principal,setPrincipal]=useState(""), [editing,setEditing]=useState(false), [scopes,setScopes]=useState<string[]>(["read"]);
  const [choices,setChoices]=useState<{value:string;label:string}[]>([]), [search,setSearch]=useState(""), [busy,setBusy]=useState(false);
  const [page,setPage]=useState(1), [size,setSize]=useState(20);
  const mutation=useRef(false), mounted=useRef(true);
  useEffect(() => { mounted.current=true; return () => {mounted.current=false;}; },[]);
  useEffect(() => {
    const controller=new AbortController(); setLoading(true);setError("");
    void request(`${base}?${query}`,{signal:controller.signal,cache:"no-store"}).then(value => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(value.grants) || value.grants.some((row:Grant) => !row.identity_id || !row.username || !Array.isArray(row.scopes))) throw new Error(t("researchDetail.invalidResponse"));
      setGrants(value.grants);
    }).catch(reason => {if(!controller.signal.aborted)setError(String(reason.message||reason));})
      .finally(() => {if(!controller.signal.aborted)setLoading(false);});
    return () => controller.abort();
  },[base,query,revision,t]);
  useEffect(() => {
    if(editing || !search.trim()) {setChoices([]);return;}
    const controller=new AbortController();
    const timer=setTimeout(() => { void request(`/api/research/principals?${new URLSearchParams({q:search.trim()})}`,{signal:controller.signal,cache:"no-store"})
      .then(value => {if(!controller.signal.aborted)setChoices(Array.isArray(value.principals) ? value.principals.map((row:any) => ({value:String(row.principal_ref||""),label:objectReferenceLabel({kind:"user",ref:String(row.principal_ref||""),label:String(row.label||"")},null)})).filter((row:any) => row.value) : []);})
      .catch(() => {if(!controller.signal.aborted)setChoices([]);}); },250);
    return () => {clearTimeout(timer);controller.abort();};
  },[search,editing]);
  const save=async (username:string, rights:string[]):Promise<void> => {
    if(mutation.current || !username.trim())return;
    mutation.current=true;setBusy(true);
    try {
      await request(base,{method:"POST",body:JSON.stringify({...Object.fromEntries(targetParams(target)),principal_ref:username.trim(),scopes:rights})});
      if(!mounted.current)return;
      notify({code:"research.sharing.grant.saved",type:"success",message:t(rights.length ? "researchSharing.grantSaved" : "researchSharing.grantRevoked")});
      setPrincipal("");setSearch("");setEditing(false);setScopes(["read"]);setRevision(value=>value+1);
    } catch(reason) {if(mounted.current)notify({code:"research.sharing.grant.failed",type:"error",message:t("researchDetail.operationFailed"),description:reason instanceof Error ? reason.message : String(reason)});}
    finally {mutation.current=false;if(mounted.current)setBusy(false);}
  };
  const edit=(row:Grant):void=>{setPrincipal(row.username);setSearch("");setEditing(true);setScopes(row.scopes);};
  const total=grants.length, visible=grants.slice((page-1)*size,page*size);
  return <div className="tr-research-sharing">
    <p className="tr-research-sharing-note">{t("researchSharing.explicitHint")}</p>
    <Form layout="vertical" onFinish={() => void save(principal,scopes)}>
      <Form.Item label={t("researchSharing.username")} required>
        <div className="tr-reference-select"><AutoComplete aria-label={t("researchSharing.username")} disabled={busy||editing} value={principal} options={choices} placeholder={t("researchSharing.usernameHint")}
          onChange={value=>{setPrincipal(value);setSearch(value);}} />{principal.trim() ? <ObjectReference icon value={{kind:"user",ref:principal.trim()}} /> : null}</div>
      </Form.Item>
      <Form.Item label={t("researchSharing.permissions")}>
        <Checkbox checked disabled>{t("researchSharing.scope.read")}</Checkbox>
        {["use","write"].map(scope=><Checkbox key={scope} disabled={busy} checked={scopes.includes(scope)} onChange={event=>setScopes(value=>event.target.checked ? [...new Set([...value,"read",scope])] : value.filter(item=>item!==scope))}>{t(`researchSharing.scope.${scope}`)}</Checkbox>)}
      </Form.Item>
      <div className="tr-research-sharing-actions"><Button htmlType="submit" type="primary" loading={busy} disabled={!principal.trim()||loading||!!error}>{t(editing ? "configuration.save" : "researchSharing.grant")}</Button>{editing ? <Button disabled={busy} onClick={()=>{setPrincipal("");setEditing(false);setScopes(["read"]);}}>{t("configuration.cancel")}</Button>:null}</div>
    </Form>
    <TRDataTable rows={visible} rowKey="identity_id" loading={loading} error={error} empty={t("researchSharing.noGrants")} pagination={{page,pageSize:size,total,onChange:(p,s)=>{setPage(p);setSize(s);}}} columns={[
      {title:t("researchSharing.username"),key:"username",render:(_:unknown,row:Grant)=><><ObjectReference value={{kind:"user",ref:row.username}} />{!row.enabled ? <Tag>{t("researchSharing.disabledUser")}</Tag>:null}</>},
      {title:t("researchSharing.permissions"),key:"scopes",render:(_:unknown,row:Grant)=><span className="tr-research-sharing-tags">{row.scopes.map(scope=><Tag key={scope}>{t(`researchSharing.scope.${scope}`,{defaultValue:scope})}</Tag>)}</span>},
      {title:t("jobs.action"),key:"action",render:(_:unknown,row:Grant)=><div className="tr-research-sharing-row-actions"><Button type="link" disabled={busy} onClick={()=>edit(row)}>{t("configuration.edit")}</Button><Popconfirm title={t("researchSharing.revokeGrantConfirm")} onConfirm={()=>void save(row.username,[])} okText={t("researchSharing.revoke")} cancelText={t("configuration.cancel")}><Button type="link" danger disabled={busy}>{t("researchSharing.revoke")}</Button></Popconfirm></div>},
    ]} />
  </div>;
}

function ResearchLinks({target}:{target:Target}):React.ReactElement {
  const {t}=useTranslation();
  const base=`/api/research/${encodeURIComponent(target.researchId)}/keycloak-share-links`, query=targetParams(target).toString();
  const [rows,setRows]=useState<ShareLink[]>([]), [error,setError]=useState(""), [loading,setLoading]=useState(true), [revision,setRevision]=useState(0);
  const [mode,setMode]=useState("one_time"), [expires,setExpires]=useState(""), [link,setLink]=useState(""), [createdId,setCreatedId]=useState(""), [validation,setValidation]=useState(""), [busy,setBusy]=useState(false);
  const [page,setPage]=useState(1), [size,setSize]=useState(20);
  const mutation=useRef(false), mounted=useRef(true), linkInput=useRef<any>(null);
  useEffect(() => {mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(() => {
    const controller=new AbortController();setLoading(true);setError("");
    void request(`${base}?${query}`,{signal:controller.signal,cache:"no-store"}).then(value=>{
      if(controller.signal.aborted)return;
      if(!Array.isArray(value.share_links)||value.share_links.some((row:ShareLink)=>!row.link_id||row.target_kind!==(target.reportId?"report":"research")||(target.reportId && row.report_id!==target.reportId))) throw new Error(t("researchDetail.invalidResponse"));
      setRows(value.share_links);
    }).catch(reason=>{if(!controller.signal.aborted)setError(String(reason.message||reason));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[base,query,revision,t]);
  const run=async (action:()=>Promise<void>,success:string):Promise<void>=>{
    if(mutation.current)return;mutation.current=true;setBusy(true);
    try{await action();if(mounted.current){notify({code:`research.sharing.link.${success}`,type:"success",message:t(`researchSharing.${success}`)});setRevision(value=>value+1);}}
    catch(reason){if(mounted.current)notify({code:"research.sharing.link.failed",type:"error",message:t("researchDetail.operationFailed"),description:reason instanceof Error?reason.message:String(reason)});}
    finally{mutation.current=false;if(mounted.current)setBusy(false);}
  };
  const create=():void=>{
    const timestamp=expires ? new Date(expires).getTime() : 0;
    if(expires && (!Number.isFinite(timestamp) || timestamp<=Date.now())) {setValidation(t("researchSharing.invalidExpiry"));return;}
    setValidation("");
    void run(async()=>{
      const response=await request(base,{method:"POST",body:JSON.stringify({...Object.fromEntries(targetParams(target)),mode,expires_at:timestamp ? timestamp/1000 : 0})});
      const token=response.share_link?.token;
      if(typeof token!=="string"||!/^[A-Za-z0-9_-]{16,512}$/.test(token)||typeof response.share_link?.link_id!=="string"||!response.share_link.link_id)throw new Error(t("researchDetail.invalidResponse"));
      const url=new URL("/app",location.origin);url.hash=new URLSearchParams({research_share:token}).toString();
      if(mounted.current){setLink(url.toString());setCreatedId(response.share_link.link_id);}
    },"linkCreated");
  };
  const copy=async():Promise<void>=>{
    try{if(!navigator.clipboard?.writeText)throw new Error("clipboard unavailable");await navigator.clipboard.writeText(link);notify({code:"research.sharing.link.copied",type:"success",message:t("researchSharing.copied")});}
    catch{linkInput.current?.select();notify({code:"research.sharing.link.copy-failed",type:"info",message:t("researchSharing.copyManually")});}
  };
  const state=(row:ShareLink):string=>Number(row.revoked_at)>0?"revoked":Number(row.expires_at)>0&&Number(row.expires_at)*1000<=Date.now()?"expired":row.mode==="one_time"&&row.redeemed_by?"redeemed":"active";
  const total=rows.length,visible=rows.slice((page-1)*size,page*size);
  return <div className="tr-research-sharing">
    <Form layout="vertical" onFinish={create}>
      <Form.Item label={t("researchSharing.linkMode")}><Select aria-label={t("researchSharing.linkMode")} disabled={busy} value={mode} onChange={setMode} options={[{value:"one_time",label:t("researchSharing.oneTime")},{value:"permanent",label:t("researchSharing.permanent")}]} /></Form.Item>
      <Form.Item label={t("researchSharing.expiry")} validateStatus={validation?"error":undefined} help={validation||undefined}><Input aria-label={t("researchSharing.expiry")} type="datetime-local" disabled={busy} value={expires} onChange={event=>{setExpires(event.target.value);setValidation("");}} /></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy} disabled={loading||!!error}>{t("researchSharing.createLink")}</Button>
    </Form>
    {link ? <div className="tr-research-share-result"><label htmlFor="tr-research-created-link">{t("researchSharing.linkOnce")}</label><div className="tr-research-share-result-row"><Input id="tr-research-created-link" ref={linkInput} readOnly value={link} onFocus={event=>event.currentTarget.select()} /><Button onClick={()=>void copy()}>{t("researchSharing.copy")}</Button></div></div>:null}
    <TRDataTable rows={visible} rowKey="link_id" loading={loading} error={error} empty={t("researchSharing.noLinks")} pagination={{page,pageSize:size,total,onChange:(p,s)=>{setPage(p);setSize(s);}}} columns={[
      {title:t("researchSharing.linkMode"),key:"mode",render:(_:unknown,row:ShareLink)=>t(row.mode==="one_time"?"researchSharing.oneTime":"researchSharing.permanent")},
      {title:t("jobs.status"),key:"status",render:(_:unknown,row:ShareLink)=><Tag>{t(`researchSharing.linkStatus.${state(row)}`)}</Tag>},
      {title:t("researchSharing.expiry"),key:"expires",render:(_:unknown,row:ShareLink)=>Number(row.expires_at)>0?formatDate(Number(row.expires_at),{dateStyle:"medium",timeStyle:"short"}):t("researchSharing.noExpiry")},
      {title:t("jobs.action"),key:"action",render:(_:unknown,row:ShareLink)=>state(row)==="active"?<Popconfirm title={t("researchSharing.revokeLinkConfirm")} description={t("researchSharing.revokeLinkHint")} onConfirm={()=>void run(async()=>{await request(`${base}/${encodeURIComponent(row.link_id)}`,{method:"PATCH",body:JSON.stringify({revoked:true})});if(mounted.current && row.link_id===createdId){setLink("");setCreatedId("");}},"linkRevoked")} okText={t("researchSharing.revoke")} cancelText={t("configuration.cancel")}><Button danger type="link" disabled={busy}>{t("researchSharing.revoke")}</Button></Popconfirm>:"—"},
    ]} />
  </div>;
}
