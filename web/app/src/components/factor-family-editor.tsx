import React,{useEffect,useRef,useState} from "react";
import {Button,Form,Input,Select,Spin,Upload} from "antd";
import {useTranslation} from "react-i18next";
import {request} from "../configuration/api.ts";
import {notify} from "../notifications/core.ts";
import {useAuth} from "../auth.tsx";
import {FactorDetail} from "./factor-detail.tsx";
import {DetailsCancelButton} from "./details-panel.tsx";
type Row=Record<string,any>;
/** Source edits are explicit operations; the directory never executes family source. */
export function FactorFamilyEditor({family,onSaved,onCancel,initialSource="custom"}:{initialSource?:"custom"|"public";family?:Row;onSaved:(row:Row)=>void;onCancel:()=>void}):React.ReactElement {
 const {t}=useTranslation(),[form]=Form.useForm();
 const [loading,setLoading]=useState(!!family),[busy,setBusy]=useState(false),[allowed,setAllowed]=useState(!family);
 const {session}=useAuth();
 const [inspection,setInspection]=useState<Row|null>(null);
 const selectedKind=Form.useWatch("source_kind",form)||"custom";
 const source=Form.useWatch("source_code",form);
 const mutation=useRef(false);
 const alias=String(family?.factor_family_alias||family?.name||family?.id||"");
 const kind=family?(family.factor_kind==="public"||family.source==="public"?"public":"custom"):selectedKind;
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
   const result=await request(family?`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}`:`/api/factor-library/families/${kind}`,{
    method:family?"PUT":"POST",body:JSON.stringify(values),
   });
   notify({code:"family.saved",type:"success",message:t("operations.saved")});onSaved({...result.factor,source:kind,factor_kind:kind,owner_username:kind==="public"?"__public_jobs__":session?.username||family?.owner_username});
  }catch(reason){notify({code:"family.save.failed",type:"error",message:reason instanceof Error?reason.message:t("operations.saveFailed")});}
  finally{mutation.current=false;setBusy(false);}
 };
 const validate=async():Promise<void>=>{
  if(mutation.current||!source)return;mutation.current=true;setBusy(true);
  try{const result=await request("/api/factor-library/families/validate",{method:"POST",body:JSON.stringify({source_code:source})});
   if(!result.valid)throw new Error(result.error||t("editor.validationFailed"));
   setInspection({...result,parameter_definitions:result.params||[]});notify({code:"family.source.valid",type:"success",message:t("editor.valid")});
  }catch(reason){setInspection(null);notify({code:"family.source.invalid",type:"error",message:reason instanceof Error?reason.message:t("editor.validationFailed")});}
  finally{mutation.current=false;setBusy(false);}
 };
 return <Spin spinning={loading}><Form form={form} layout="vertical" requiredMark={false} initialValues={{source_kind:session?.role==="super_admin"?initialSource:"custom"}} disabled={busy||loading} onValuesChange={()=>setInspection(null)} onFinish={save}>
  {!family&&session?.role==="super_admin"?<Form.Item name="source_kind" label={t("library.visibility")}><Select aria-label={t("library.visibility")} options={[{value:"custom",label:t("library.scopes.mine")},{value:"public",label:t("library.scopes.public")}]} /></Form.Item>:null}
  <Form.Item name="chinese_name" label={t("editor.name")}><Input aria-label={t("editor.name")} maxLength={256}/></Form.Item>
  <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{minRows:2,maxRows:5}}/></Form.Item>
  <div className="tr-inline-actions"><Upload accept=".py" showUploadList={false} disabled={busy||loading||!allowed} beforeUpload={async file=>{
   if(mutation.current)return Upload.LIST_IGNORE;
   if(file.size>1024*1024){notify({code:"family.source.tooLarge",type:"error",message:t("editor.sourceTooLarge")});return Upload.LIST_IGNORE;}
   mutation.current=true;setBusy(true);
   try{form.setFieldValue("source_code",await file.text());setInspection(null);}
   catch{notify({code:"family.source.readFailed",type:"error",message:t("loadFailed")});}
   finally{mutation.current=false;setBusy(false);}return false;
  }}><Button>{t("editor.importSource")}</Button></Upload><Button disabled={!source||busy||loading} onClick={()=>void validate()}>{t("editor.validate")}</Button></div>
  <Form.Item name="source_code" label={t("editor.source")} rules={[{required:true,whitespace:true}]}><Input.TextArea aria-label={t("editor.source")} className="tr-source-input" autoSize={{minRows:14,maxRows:30}} spellCheck={false}/></Form.Item>
  {inspection?<FactorDetail detail={inspection}/>:null}
  <div className="tr-inline-actions"><Button type="primary" htmlType="submit" aria-label={t("save")} aria-busy={busy} loading={busy} disabled={!allowed||busy||loading}>{t("save")}</Button><DetailsCancelButton disabled={busy} closePanel={false} onCancel={onCancel}/></div>
 </Form></Spin>;
}
