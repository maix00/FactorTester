import React,{useEffect,useRef,useState} from "react";
import {Button,Input,Modal,Select,Spin,Tabs,Typography} from "antd";
import {useTranslation} from "react-i18next";
import {useAuth} from "../auth.tsx";
import {familyConfigurationKey} from "../catalog-search.ts";
import {factorSourceKey} from "../factor-parameters.ts";
import {request} from "../configuration/api.ts";
import {notify} from "../notifications/core.ts";
import {FactorDetail} from "./factor-detail.tsx";
import {ObjectReference} from "./object-reference.tsx";
import {PropertyGroups} from "./property-groups.tsx";
import {TRDataTable} from "./data-table.tsx";
type Row=Record<string,any>;
/** Only explicit source/version tabs hydrate executable-source metadata. */
export function FactorFamilyDetail({family,fingerprint,onChanged}:{family:Row;fingerprint?:string;onChanged?:()=>void}):React.ReactElement {
 const {t}=useTranslation(),{session}=useAuth();
 const [tab,setTab]=useState('overview'),[version,setVersion]=useState(fingerprint||'current'),[exactVersion,setExactVersion]=useState('');
 const [versions,setVersions]=useState<Row[]|null>(null),[versionLimit,setVersionLimit]=useState(100),[source,setSource]=useState<{version:string;value:Row}|null>(null),[members,setMembers]=useState<Row[]|null>(null);
 const [loading,setLoading]=useState(false),[retry,setRetry]=useState(0),[impact,setImpact]=useState<Row|null>(null),[action,setAction]=useState<'delete'|'transfer'>('delete'),[busy,setBusy]=useState(false);
 const loaded=useRef({history:0,source:'',members:false});
 const [page,setPage]=useState(1),[size,setSize]=useState(10);const mutation=useRef(false);
 const alias=String(family.factor_family_alias||family.name||family.id||''),kind=family.source==='public'||family.factor_kind==='public'?'public':'custom';
 const query=new URLSearchParams(kind==='custom'&&family.owner_username?{owner_username:String(family.owner_username)}:{});
 const endpoint=`/api/factor-library/family-sources/${kind}/${encodeURIComponent(alias)}/versions`;
 const canManage=!!onChanged&&(kind==='public'?session?.role==='super_admin':family.owner_username===session?.username);
 useEffect(()=>{
  if(tab==='overview'&&version==='current'&&!fingerprint){setLoading(false);return;}
  const controller=new AbortController();const tasks:Promise<void>[]=[];
  if(tab==='members'){
   if(!loaded.current.members)tasks.push(request('/api/factor-library/factors',{signal:controller.signal}).then(result=>{
    if(controller.signal.aborted)return;loaded.current.members=true;setMembers((result.factors||[]).filter((row:Row)=>factorSourceKey(row)===familyConfigurationKey(family)));
   }));
  }else{
   if(loaded.current.history<versionLimit)tasks.push(request(`${endpoint}?${query}&limit=${versionLimit}`,{signal:controller.signal}).then(history=>{
    if(controller.signal.aborted)return;loaded.current.history=versionLimit;setVersions(history.versions||[]);
   }));
   if(loaded.current.source!==version)tasks.push(request(`${endpoint}/${encodeURIComponent(version)}?${query}`,{signal:controller.signal}).then(selected=>{
    if(controller.signal.aborted)return;loaded.current.source=version;setSource({version,value:selected});
   }));
  }
  if(!tasks.length){setLoading(false);return;}
  setLoading(true);
  void Promise.all(tasks).catch(reason=>{if(!controller.signal.aborted)notify({code:'family.detail.load',type:'error',message:reason.message});})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[tab,version,versionLimit,alias,kind,family.owner_username,fingerprint,retry]);
 const change=async(next:'delete'|'transfer'):Promise<void>=>{
  if(mutation.current)return;mutation.current=true;setBusy(true);
  try{const value=await request(`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}/impact`);if(!value.revision)throw new Error(t('editor.missingIdentity'));setImpact(value);setAction(next);}
  catch(reason){notify({code:'family.impact.failed',type:'error',message:(reason as Error).message});}
  finally{mutation.current=false;setBusy(false);}
 };
 const confirm=async():Promise<void>=>{
  if(mutation.current||!impact)return;mutation.current=true;setBusy(true);
  try{const base=`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}`;
   await request(action==='delete'?`${base}?revision=${encodeURIComponent(impact.revision)}`:`${base}/transfer`,{method:action==='delete'?'DELETE':'POST',...(action==='transfer'?{body:JSON.stringify({revision:impact.revision})}:{})});
   setImpact(null);notify({code:'family.change.saved',type:'success',message:t(action==='delete'?'operations.deleted':'operations.saved')});onChanged?.();
  }catch(reason){setImpact(null);notify({code:'family.change.failed',type:'error',message:(reason as Error).message});}
  finally{mutation.current=false;setBusy(false);}
 };
 const selectedSource=source?.version===version?source.value:null;
 const shown=selectedSource?{...family,...selectedSource}:family;
 return <section><Tabs activeKey={tab} onChange={value=>{setTab(value);setPage(1);}} items={['overview','source','versions','members'].map(key=>({key,label:t(`familyDetail.${key}`)}))}/>
 {tab==='overview'?<FactorDetail detail={shown}/>:<Spin spinning={loading}>
  {tab==='source'?<><Select aria-label={t('library.version')} value={version} onChange={setVersion} style={{width:'100%'}} options={[{value:'current',label:t('familyDetail.current')},...(versions||[]).map(row=>({value:String(row.family_formula_fingerprint),label:String(row.family_formula_fingerprint).slice(0,12)})),...(version!=='current'&&!versions?.some(row=>row.family_formula_fingerprint===version)?[{value:version,label:version.slice(0,12)}]:[])]}/><Typography.Paragraph copyable={selectedSource?.source_code?{text:selectedSource!.source_code}:false}><pre className="tr-source-input tr-family-source"><code>{selectedSource?.source_code||''}</code></pre></Typography.Paragraph></>:
   tab==='versions'?<><TRDataTable<Row> rows={(versions||[]).slice((page-1)*size,page*size)} rowKey="family_formula_fingerprint" pagination={{page,pageSize:size,total:versions?.length||0,onChange:(p,s)=>{setPage(p);setSize(s);}}} columns={[
    {key:'version',title:t('library.version'),render:(_,row)=><button className="tr-table-link" onClick={()=>{setVersion(row.family_formula_fingerprint);setTab('source');}}>{String(row.family_formula_fingerprint).slice(0,12)}</button>},
    {key:'subject',title:t('library.description'),dataIndex:'subject'},
   ]}/>{versions?.length===versionLimit&&versionLimit<500?<Button onClick={()=>setVersionLimit(value=>value+100)}>{t('familyDetail.moreVersions')}</Button>:null}
    <Input.Search aria-label={t('familyDetail.exactVersion')} placeholder={t('familyDetail.exactVersion')} value={exactVersion} onChange={event=>setExactVersion(event.target.value)} onSearch={value=>{if(/^[0-9a-f]{64}$/i.test(value)){setVersion(value);setTab('source');}else notify({code:'family.version.invalid',type:'error',message:t('familyDetail.invalidVersion')});}}/></>:
   <TRDataTable<Row> rows={(members||[]).slice((page-1)*size,page*size)} rowKey={row=>String(row.ref||row.factor_ref)} pagination={{page,pageSize:size,total:members?.length||0,onChange:(p,s)=>{setPage(p);setSize(s);}}} columns={[
    {key:'factor',title:t('catalog.factors'),render:(_,row)=><ObjectReference value={{kind:'factor',ref:String(row.ref||row.factor_ref),label:row.alias||row.factor_alias,owner:row.owner_username}}/>},
    {key:'owner',title:t('library.owner'),render:(_,row)=><ObjectReference value={{kind:'user',ref:String(row.owner_username||''),label:row.owner_alias}}/>},
   ]}/>}
   <Button type="text" onClick={()=>{loaded.current={history:0,source:"",members:false};setRetry(value=>value+1);}}>{t('configuration.reload')}</Button>
 </Spin>}
 {canManage?<div className="tr-inline-actions"><Button danger disabled={busy} onClick={()=>void change('delete')}>{t('familyDetail.delete')}</Button>{session?.role==='super_admin'?<Button disabled={busy} onClick={()=>void change('transfer')}>{t(kind==='custom'?'familyDetail.makePublic':'familyDetail.makePrivate')}</Button>:null}</div>:null}
 <Modal open={!!impact} title={t(action==='delete'?'familyDetail.delete':'familyDetail.transfer')} onCancel={()=>{if(!busy)setImpact(null);}} onOk={()=>void confirm()} confirmLoading={busy} okButtonProps={{danger:action==='delete'}} cancelButtonProps={{disabled:busy}} okText={t('familyDetail.confirm')} cancelText={t('configuration.cancel')}>
  <PropertyGroups groups={[{key:'impact',title:t('familyDetail.impact'),items:[{key:'factors',label:t('catalog.factors'),value:impact?.factor_count},{key:'sets',label:t('catalog.sets'),value:impact?.factor_sets?.length||0},{key:'accounts',label:t('library.owner'),value:new Set((impact?.registrations||[]).map((row:Row)=>row.username)).size}]}]}/>
 </Modal></section>;
}
