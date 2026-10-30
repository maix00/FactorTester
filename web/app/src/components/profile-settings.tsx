import React, { useEffect, useState } from "react";
import { Alert, Button, Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { TRDataTable } from "./data-table.tsx";
import { PropertyGroups } from "./property-groups.tsx";
type Profile = Record<string, any>;
/** Directory identity and access are resolved by Manager, never inferred from a display name. */
export function ProfileSettings():React.ReactElement {
 const {t}=useTranslation();
 const [query,setQuery]=useState(""),[page,setPage]=useState(1),[size,setSize]=useState(20),[reload,setReload]=useState(0);
 const [rows,setRows]=useState<Profile[]>([]),[total,setTotal]=useState(0),[loading,setLoading]=useState(true),[error,setError]=useState("");
 const [selected,setSelected]=useState<Profile|null>(null),[detail,setDetail]=useState<Profile|null>(null),[detailError,setDetailError]=useState("");
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);setError("");
  const timer=setTimeout(()=>void request(`/api/client/profile-directory?${new URLSearchParams({scope:"mine",query,page:String(page),page_size:String(size)})}`,{signal:controller.signal})
   .then(data=>{if(!controller.signal.aborted){setRows(data.items||[]);setTotal(data.total||0);}})
   .catch(reason=>{if(!controller.signal.aborted)setError(reason.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);}),250);
  return()=>{clearTimeout(timer);controller.abort();};
 },[query,page,size,reload]);
 useEffect(()=>{
  setDetail(null);setDetailError("");if(!selected)return;
  const controller=new AbortController();
  void request(`/api/client/profile-directory/profile?${new URLSearchParams({scope:"mine",profile_key:String(selected.profile_key)})}`,{signal:controller.signal})
   .then(data=>{if(!controller.signal.aborted)setDetail(data.profile);}).catch(reason=>{if(!controller.signal.aborted)setDetailError(reason.message);});
  return()=>controller.abort();
 },[selected,reload]);
 if(selected)return <div className="tr-settings-browser"><Button onClick={()=>setSelected(null)}>{t("settingsPanel.profileList")}</Button>
  {detailError?<Alert type="error" message={detailError} action={<Button onClick={()=>setReload(n=>n+1)}>{t("retry")}</Button>}/>:!detail?<Spin/>:<PropertyGroups groups={[{key:"profile",title:detail.display_name||detail.profile_id,items:[
    {key:"name",label:t("editor.name"),value:detail.display_name||detail.profile_id},
    {key:"owner",label:t("library.owner"),value:detail.owner_alias||detail.owner_ref},
    {key:"id",label:t("settingsPanel.profileIdentity"),value:detail.profile_key,wide:true},
    {key:"server",label:t("settingsPanel.sections.server"),value:detail.source_server_id},
    {key:"visibility",label:t("library.visibility"),value:detail.visibility,render:value=>t(`research.visibility.${value}`,{defaultValue:String(value)})},
  ]}]}/>}
 </div>;
 return <div className="tr-settings-browser"><Input.Search allowClear aria-label={t("library.search")} placeholder={t("library.search")} value={query} onChange={event=>{setQuery(event.target.value);setPage(1);}}/>
  <TRDataTable rows={rows} rowKey="profile_key" loading={loading} error={error} pagination={{page,pageSize:size,total,onChange:(p,s)=>{setPage(p);setSize(s);}}} columns={[
   {key:"name",title:t("editor.name"),render:(_,row)=><button className="tr-table-link" onClick={()=>setSelected(row)}>{row.display_name||row.profile_id}</button>},
   {key:"owner",title:t("library.owner"),render:(_,row)=>row.owner_alias||row.owner_ref},
  ]}/></div>;
}
