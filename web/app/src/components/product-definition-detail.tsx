import React,{useState} from "react";
import {useTranslation} from "react-i18next";
import {PropertyGroups} from "./property-groups.tsx";
import {TRDataTable} from "./data-table.tsx";
import {ObjectReference} from "./object-reference.tsx";
type Row=Record<string,any>;
/** Definitions display authored paths; opening details does not expand all products. */
export function ProductDefinitionDetail({value,category=false}:{value:Row;category?:boolean}):React.ReactElement {
 const {t}=useTranslation(),[page,setPage]=useState(1),[size,setSize]=useState(10),[memberPage,setMemberPage]=useState(1),[memberSize,setMemberSize]=useState(10);
 const owner=String(value.owner_username||value.owner_ref||"");
 const rows:Row[]=category?(value.items||[]):(value.paths||[]).map((path:string)=>({path}));
 return <section><PropertyGroups groups={[{key:"definition",title:t("details"),items:[
  {key:"name",label:t("editor.name"),value:value.name||value.alias||value.title_zh},
  {key:"owner",label:t("library.owner"),value:owner,render:()=> <ObjectReference value={{kind:"user",ref:owner,label:value.owner_alias||owner}}/>},
  ...(!category?[{key:"count",label:t("catalog.products"),value:value.product_count??value.product_names?.length}]:[]),
 ]}]}/><TRDataTable<Row> rows={rows.slice((page-1)*size,page*size)} rowKey={row=>String(row.label||row.path)}
  pagination={{page,pageSize:size,total:rows.length,hideOnSinglePage:true,onChange:(p,s)=>{setPage(p);setSize(s);}}}
  columns={category?[{key:"label",title:t("category.entryLabel"),dataIndex:"label"},{key:"paths",title:t("category.paths"),render:(_,row)=><ul className="tr-definition-paths">{(row.paths||[]).map((path:string)=><li key={path}><code>{path}</code></li>)}</ul>}]:[{key:"path",title:t("productGroup.paths"),render:(_,row)=><code>{row.path}</code>}]}/>
 {Array.isArray(value.product_names)&&value.product_names.length?<details><summary>{t("catalog.products")}</summary><TRDataTable<{name:string}> rows={value.product_names.slice((memberPage-1)*memberSize,memberPage*memberSize).map((name:string)=>({name}))} rowKey="name"
  pagination={{page:memberPage,pageSize:memberSize,total:value.product_names.length,onChange:(p,s)=>{setMemberPage(p);setMemberSize(s);}}}
  columns={[{key:"name",title:t("catalog.products"),render:(_,row)=><ObjectReference value={{kind:"product",ref:row.name,label:row.name}}/>}]}/></details>:null}
 </section>;
}
