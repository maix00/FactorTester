import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
type Page={slug:string;title:string;section_title?:string};
export function DocsSettings():React.ReactElement {
 const article=useRef<HTMLElement>(null);const [anchor,setAnchor]=useState("");
 const {t}=useTranslation();const [pages,setPages]=useState<Page[]>([]),[slug,setSlug]=useState(""),[html,setHTML]=useState(""),[title,setTitle]=useState("");
 const [query,setQuery]=useState(""),[error,setError]=useState(""),[loading,setLoading]=useState(true),[reload,setReload]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();setError("");
  void request("/api/docs/index",{signal:controller.signal}).then(data=>{
   if(controller.signal.aborted)return;
   setPages((data.sections||[]).flatMap((section:{title:string;pages:Page[]})=>(section.pages||[]).map(page=>({...page,section_title:section.title}))));
   setSlug(current=>current||data.default_page||"");
  }).catch(reason=>{if(!controller.signal.aborted){setError(reason.message);setLoading(false);}});
  return()=>controller.abort();
 },[reload]);
 useEffect(()=>{
  if(!slug)return;const controller=new AbortController();setLoading(true);setError("");setHTML("");
  void request(`/api/docs/pages/${encodeURIComponent(slug)}`,{signal:controller.signal}).then(data=>{
   if(!controller.signal.aborted){setHTML(data.html||"");setTitle(data.title||slug);}
  }).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[slug,reload]);
 useEffect(()=>{if(anchor&&html)Array.from(article.current?.querySelectorAll("[id]")||[]).find(node=>node.id===anchor)?.scrollIntoView({block:"start"});},[html,anchor]);
 return <div className="tr-settings-browser">
  <Input.Search allowClear aria-label={t("settingsPanel.searchDocs")} placeholder={t("settingsPanel.searchDocs")} value={query} onChange={event=>setQuery(event.target.value)}/>
  <Select aria-label={t("settingsPanel.sections.docs")} value={slug||undefined} onChange={value=>{setAnchor("");setSlug(value);}} options={pages.filter(page=>`${page.title} ${page.section_title}`.toLowerCase().includes(query.toLowerCase())).map(page=>({value:page.slug,label:page.title}))}/>
  {error?<Alert type="error" message={error} action={<Button onClick={()=>setReload(n=>n+1)}>{t("retry")}</Button>}/>:loading?<Spin/>:<article ref={article} className="tr-technical-document" onClick={event=>{
   const link=(event.target as HTMLElement).closest('a');if(!link)return;
   const href=link.getAttribute('href')||"";
   if(href.startsWith('/docs/')||href.startsWith('#')){event.preventDefault();setAnchor(decodeURIComponent(href.split('#')[1]||''));if(href.startsWith('/docs/'))setSlug(decodeURIComponent(href.split('#')[0].slice(6)));}
  }}><h3>{title}</h3>{/* Only the compiled /api/docs/pages response: Manager sanitizes HTML with nh3. */}
   <div dangerouslySetInnerHTML={{__html:html}}/></article>}
 </div>;
}
