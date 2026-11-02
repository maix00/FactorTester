import React,{useEffect,useRef,useState} from "react";
import {Button,Empty,Spin,Tree} from "antd";
import {useTranslation} from "react-i18next";
import {request} from "../configuration/api.ts";
import {usePageInstance} from "../page-instance.ts";
import {useCompactLayout} from "../configuration/layout.ts";
import {notify} from "../notifications/core.ts";
type Row=Record<string,any>;
type Node={key:string;title:React.ReactNode;children?:Node[];isLeaf:boolean;raw:Row;more?:boolean};
/** The shared catalog API owns hierarchy and paging; Ant Tree owns virtualization. */
export function ProductTree():React.ReactElement {
 const {t}=useTranslation(),instance=usePageInstance(),compact=useCompactLayout();
 const [nodes,setNodes]=useState<Node[]>([]),[loading,setLoading]=useState(true);
 const lifecycle=useRef<AbortController|null>(null),pending=useRef(new Map<string,Promise<void>>());
 const convert=(rows:Row[]):Node[]=>rows.map(row=>({key:String(row.key),title:String(row.title==="Product Lists"?t("catalog.products"):row.title||row.key),
  isLeaf:!row.lazy&&!row.children?.length,raw:row,...(row.children?.length?{children:convert(row.children)}:{})}));
 useEffect(()=>{
  const controller=new AbortController();lifecycle.current=controller;setLoading(true);setNodes([]);pending.current.clear();
  void request("/api/product-library/tree",{signal:controller.signal})
   .then(value=>{if(!controller.signal.aborted)setNodes(convert(value.tree||[]));})
   .catch(reason=>{if(!controller.signal.aborted)notify({code:"product.tree.load",type:"error",message:reason.message});})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[t]);
 const load=(path:string,page=1):Promise<void>=>{
  const key=JSON.stringify([path,page]),old=pending.current.get(key);if(old)return old;
  const signal=lifecycle.current?.signal;
  const task=request(`/api/product-library/contract-tree?${new URLSearchParams({path,page:String(page),limit:"50"})}`,{signal})
   .then(result=>{
    if(signal?.aborted)return;
    const next=convert(result.nodes||[]);
    if(result.has_more)next.push({key:`${path}#tr-page:${page+1}`,title:<Button type="link" size="small" onClick={event=>{event.stopPropagation();void load(path,page+1).catch(()=>undefined);}}>{t("catalogActions.moreProducts")}</Button>,isLeaf:true,raw:{},more:true});
    const replace=(items:Node[]):Node[]=>items.map(node=>node.key===path?{...node,children:[...(page===1?[]:node.children?.filter(child=>!child.more)||[]),...next]}:node.children?{...node,children:replace(node.children)}:node);
    setNodes(current=>replace(current));
   }).catch(reason=>{if(!signal?.aborted)notify({code:`product.tree.leaves.${path}`,type:"error",message:reason.message});throw reason;});
  pending.current.set(key,task);
  void task.finally(()=>{if(pending.current.get(key)===task)pending.current.delete(key);}).catch(()=>undefined);
  return task;
 };
 return <Spin spinning={loading}><section className="tr-product-tree" aria-label={t("catalog.tree")}>
  {!loading&&!nodes.length?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE}/>:<Tree<Node> virtual height={compact?360:520} blockNode showLine treeData={nodes}
   loadData={node=>node.isLeaf||node.children?.length?Promise.resolve():load(String(node.key))}
   onSelect={(_,info)=>{const row=info.node.raw;if(row.product_name)instance.open("product-detail",{productName:String(row.product_name),productTitle:String(row.desc||row.product_name),...(row.contract_uid?{contractUid:String(row.contract_uid)}:{})});}}/>}
 </section></Spin>;
}
