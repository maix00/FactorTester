import React,{useEffect,useRef,useState} from "react";
import {Button,Form,Input,Spin} from "antd";
import {useTranslation} from "react-i18next";
import {request} from "../configuration/api.ts";
import {notify} from "../notifications/core.ts";
import {DetailsCancelButton} from "./details-panel.tsx";
type Row=Record<string,any>;
/** Source edits are explicit operations; the directory never executes family source. */
export function FactorFamilyEditor({family,onSaved,onCancel}:{family?:Row;onSaved:(row:Row)=>void;onCancel:()=>void}):React.ReactElement {
 const {t}=useTranslation(),[form]=Form.useForm();
 const [loading,setLoading]=useState(!!family),[busy,setBusy]=useState(false),[allowed,setAllowed]=useState(!family);
 const mutation=useRef(false);
 const alias=String(family?.factor_family_alias||family?.name||family?.id||"");
 const kind=family?.factor_kind==="public"||family?.source==="public"?"public":"custom";
 useEffect(()=>{
  if(!family)return;
  const controller=new AbortController();setLoading(true);
  request(`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}`,{signal:controller.signal})
   .then(value=>{if(!controller.signal.aborted){form.setFieldsValue(value.factor);setAllowed(value.factor?.can_edit===true);}})
   .catch(reason=>{if(!controller.signal.aborted)notify({code:"family.source.load",type:"error",message:reason.message});})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[alias,kind,form]);
 const save=async(values:Row):Promise<void>=>{
  if(mutation.current||!allowed)return;mutation.current=true;setBusy(true);
  try{
   const result=await request(family?`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}`:"/api/factor-library/families/custom",{
    method:family?"PUT":"POST",body:JSON.stringify(values),
   });
   notify({code:"family.saved",type:"success",message:t("operations.saved")});onSaved(result.factor);
  }catch(reason){notify({code:"family.save.failed",type:"error",message:reason instanceof Error?reason.message:t("operations.saveFailed")});}
  finally{mutation.current=false;setBusy(false);}
 };
 return <Spin spinning={loading}><Form form={form} layout="vertical" requiredMark={false} disabled={busy||loading} onFinish={save}>
  <Form.Item name="chinese_name" label={t("editor.name")}><Input aria-label={t("editor.name")} maxLength={256}/></Form.Item>
  <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{minRows:2,maxRows:5}}/></Form.Item>
  <Form.Item name="source_code" label={t("editor.source")} rules={[{required:true,whitespace:true}]}><Input.TextArea aria-label={t("editor.source")} className="tr-source-input" autoSize={{minRows:14,maxRows:30}} spellCheck={false}/></Form.Item>
  <div className="tr-inline-actions"><Button type="primary" htmlType="submit" loading={busy} disabled={!allowed}>{t("save")}</Button><DetailsCancelButton disabled={busy} closePanel={false} onCancel={onCancel}/></div>
 </Form></Spin>;
}
