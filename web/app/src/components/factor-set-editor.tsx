import React,{useEffect,useRef,useState} from "react";
import {Button,Form,Input,Select,Spin} from "antd";
import {useTranslation} from "react-i18next";
import {request} from "../configuration/api.ts";
import {notify} from "../notifications/core.ts";
import {DetailsCancelButton} from "./details-panel.tsx";
type Row=Record<string,any>;
/** Immutable member descriptors are obtained from the authority, never reconstructed. */
export function FactorSetEditor({value,onSaved,onCancel}:{value?:Row;onSaved:(row:Row)=>void;onCancel:()=>void}):React.ReactElement {
 const {t}=useTranslation(),[form]=Form.useForm(),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[ready,setReady]=useState(false);
 const [rows,setRows]=useState<Row[]>([]),[setID]=useState(()=>String(value?.set_id||crypto.randomUUID()));
 const frozen=useRef(new Map<string,Row>()),pending=useRef(false);
 const ref=String(value?.target_ref||value?.ref||"");
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);setReady(false);
  void Promise.all([request("/api/factor-library/factors",{signal:controller.signal}),ref?request(`/api/factor-library/factor-sets/descriptor?${new URLSearchParams({target_ref:ref,owner_username:String(value?.owner_username||"")})}`,{signal:controller.signal}):Promise.resolve(null)])
   .then(([catalog,detail])=>{
    if(controller.signal.aborted)return;
    const descriptor=detail?.descriptor?.manifest,members=descriptor?.identity?.members||[];
    frozen.current=new Map(members.map((member:Row)=>[String(member.ref),member]));
    setRows([...new Map([...catalog.factors,...members].map((row:Row)=>[String(row.ref||row.factor_ref),row])).values()] as Row[]);
    setReady(true);form.setFieldsValue({alias:descriptor?.alias||value?.title_zh||"",description:descriptor?.description||value?.description_zh||"",members:members.map((member:Row)=>member.ref)});
   }).catch(reason=>{if(!controller.signal.aborted)notify({code:"factorSet.load",type:"error",message:reason.message});})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[ref,form]);
 const save=async(fields:{alias:string;description?:string;members:string[]}):Promise<void>=>{
  if(pending.current||!ready)return;pending.current=true;setBusy(true);
  try{
   const members:Row[]=[];
   for(let start=0;start<fields.members.length;start+=4){
    members.push(...await Promise.all(fields.members.slice(start,start+4).map(async id=>{
     const known=frozen.current.get(id);if(known)return known;
     const owner=rows.find(row=>(row.ref||row.factor_ref)===id)?.owner_username;
     const result=await request(`/api/factor-library/factors/detail?${new URLSearchParams({factor_ref:id,...(owner?{owner_username:String(owner)}:{})})}`);
     if(result.factor?.ref!==id)throw new Error(t("editor.missingIdentity"));return result.factor;
    })));
   }
   const result=await request("/api/factor-library/factor-sets",{method:"POST",body:JSON.stringify({definition:{set_id:setID,alias:fields.alias.trim(),description:fields.description||"",members},...(ref?{replace_target_ref:ref}:{})})});
   notify({code:"factorSet.saved",type:"success",message:t("operations.saved")});onSaved(result.factor_set);
  }catch(reason){notify({code:"factorSet.save.failed",type:"error",message:reason instanceof Error?reason.message:t("operations.saveFailed")});}
  finally{pending.current=false;setBusy(false);}
 };
 return <Spin spinning={loading}><Form form={form} layout="vertical" disabled={loading||busy} onFinish={save} requiredMark={false}>
  <Form.Item name="alias" label={t("editor.name")} rules={[{required:true,whitespace:true}]}><Input aria-label={t("editor.name")} maxLength={256}/></Form.Item>
  <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{minRows:2,maxRows:5}}/></Form.Item>
  <Form.Item name="members" label={t("catalog.factors")} rules={[{required:true,type:"array",min:1}]}><Select aria-label={t("catalog.factors")} mode="multiple" showSearch optionFilterProp="label" options={rows.map(row=>({value:String(row.ref||row.factor_ref),label:String(row.alias||row.factor_alias||row.ref||row.factor_ref)}))}/></Form.Item>
  <div className="tr-inline-actions"><Button type="primary" htmlType="submit" loading={busy} disabled={!ready}>{t("save")}</Button><DetailsCancelButton disabled={busy} closePanel={false} onCancel={onCancel}/></div>
 </Form></Spin>;
}
