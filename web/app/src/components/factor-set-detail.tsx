import React,{useEffect,useState} from "react";
import {Empty} from "antd";
import {useTranslation} from "react-i18next";
import {request} from "../configuration/api.ts";
import {notify} from "../notifications/core.ts";
import {TRDataTable} from "./data-table.tsx";
import {PropertyGroups} from "./property-groups.tsx";
import {ObjectReference} from "./object-reference.tsx";
type Row=Record<string,any>;
export function FactorSetDetail({value}:{value:Row}):React.ReactElement {
 const {t}=useTranslation(),[page,setPage]=useState(1),[size,setSize]=useState(20);
 const [detail,setDetail]=useState<Row|null>(null),[loading,setLoading]=useState(false);
 const ref=String(value.target_ref||value.ref||""),owner=String(value.owner_username||"");
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);
  void request(`/api/factor-library/factor-sets/detail?${new URLSearchParams({target_ref:ref,owner_username:owner,offset:String((page-1)*size),limit:String(size)})}`,{signal:controller.signal})
   .then(result=>{if(!controller.signal.aborted)setDetail(result.factor_set);})
   .catch(reason=>{if(!controller.signal.aborted){setDetail(null);notify({code:"factorSet.detail.load",type:"error",message:reason.message});}})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[ref,owner,page,size]);
 const rows=detail?.related_references||[];
 return <section><PropertyGroups groups={[{key:"set",title:t("details"),items:[
  {key:"description",label:t("library.description"),value:value.description_zh||detail?.description_zh},
  {key:"owner",label:t("library.owner"),value:owner,render:()=> <ObjectReference value={{kind:"user",ref:owner,label:value.owner_alias||owner}}/>},
  {key:"count",label:t("catalog.factors"),value:detail?.member_count??value.member_count},
 ]}]}/>{!loading&&!detail?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE}/>:<TRDataTable<Row> rows={rows} rowKey="target_ref" loading={loading}
  pagination={{page,pageSize:size,total:Number(detail?.member_count||value.member_count||0),onChange:(p,s)=>{setPage(p);setSize(s);}}}
  columns={[{key:"factor",title:t("catalog.factors"),render:(_,row)=><ObjectReference value={{kind:"factor",ref:String(row.target_ref),label:String(row.label||row.target_ref)}}/>}]}/>}</section>;
}
