import React,{useEffect,useRef,useState} from "react";
import {Button,Collapse,Empty,Select,Spin,Tag} from "antd";
import {ReloadOutlined} from "@ant-design/icons";
import {useTranslation} from "react-i18next";
import {useAuth} from "../auth.tsx";
import {usePageInstance} from "../page-instance.ts";
import {useLocalResearchContext} from "../local-research-context.tsx";
import {request} from "../configuration/api.ts";
import {assistantResearchContexts} from "../assistant-research-context.ts";
import {notify} from "../notifications/core.ts";
import {formatDate} from "../format.ts";
import {reportBranches,selectReportBranch} from "../research-model.ts";
import {FunctionPage} from "../components/function-page.tsx";
import {LocalResearchDetail} from "../components/local-research-page.tsx";
import {PropertyGroups} from "../components/property-groups.tsx";
import {ObjectReference} from "../components/object-reference.tsx";
import {ResearchEdit} from "../components/research-edit.tsx";
import {ResearchRelations} from "../components/research-relations.tsx";
import {ResearchSharing} from "../components/research-sharing.tsx";
import {ReportMarkdown} from "../components/report-markdown.tsx";
import {ReportExport} from "../components/report-export.tsx";
import {ReportBranchReader} from "../components/report-branch-reader.tsx";
type Row=Record<string,any>;
export function ResearchDetailPage():React.ReactElement {
 const {session}=useAuth(),instance=usePageInstance();
 const identity=session as typeof session & {keycloak_issuer?:string;keycloak_subject?:string};
 return <ResearchDetailForSession key={JSON.stringify([identity?.keycloak_issuer,identity?.keycloak_subject,instance.args])}/>;
}
function ResearchDetailForSession():React.ReactElement {
 const {t}=useTranslation(),instance=usePageInstance(),{session}=useAuth(),local=useLocalResearchContext();
 const principal=session?.username||"",id=instance.args.researchId||"",reportId=instance.args.reportId;
 const [detail,setDetail]=useState<Row|null>(null),[selected,setSelected]=useState<Row|null>(null);
 const [error,setError]=useState(""),[revision,setRevision]=useState(0),[editingResearch,setEditingResearch]=useState(false);
 const [section,setSection]=useState("details"),[selectedPublicationID,setSelectedPublicationID]=useState("");
 const [readingChapter,setReadingChapter]=useState({publicationID:"",chapterID:""});
 const [importingReport,setImportingReport]=useState(false),pendingImport=useRef(false);
 const syncLocalReports=local.requestSync,refresh=():void=>setRevision(value=>value+1);
 const openResearch=(researchId:string,title:string):void=>instance.open("research-detail",{researchId,researchTitle:title});
 useEffect(()=>{
  if(instance.args.localResearch)return;
  const controller=new AbortController();setError("");
  void Promise.all([request(`/api/research/${encodeURIComponent(id)}`,{signal:controller.signal}),
   reportId?request(`/api/research/${encodeURIComponent(id)}/reports`,{signal:controller.signal}):Promise.resolve(null)
  ]).then(([research,reports])=>{
   if(controller.signal.aborted)return;
   setDetail(research.research||research);
   if(reportId){const row=reports?.reports?.find((value:Row)=>value.report_id===reportId);
    if(!row)throw new Error(t("objectReference.notFoundOrAmbiguous"));setSelected(row);}
  }).catch(reason=>{if(!controller.signal.aborted){setError(String(reason.message||reason));notify({code:`research.detail.${id}`,type:"error",message:String(reason.message||reason)});}});
  return()=>controller.abort();
 },[id,reportId,revision,instance.args.localResearch,t]);
 useEffect(()=>{
  const allowed=!error&&!instance.args.localResearch&&instance.active!==false&&detail?.research_id===id&&detail?.access?.can_view===true;
  assistantResearchContexts.set(instance.id,allowed?{researchId:id,title:String(detail!.title||id),section}:null);
  return()=>assistantResearchContexts.set(instance.id,null);
 },[error,detail,id,section,instance.id,instance.active,instance.args.localResearch]);
 const title=String(detail?.title||instance.args.researchTitle||id),linkedResearch=id;
 const availableReportBranches=selected?reportBranches(selected):[];
 const selectedReportBranch=selected?selectReportBranch(selected,selectedPublicationID):undefined;
 const selectedPublicationBranch=selectedReportBranch?.source_kind==="publication"?selectedReportBranch:undefined;
 const content=instance.args.localResearch?local.client&&local.capabilities?<LocalResearchDetail
  client={local.client} capabilities={local.capabilities}
  item={{research_id:id,profile_id:instance.args.profileId||"self",title:instance.args.researchTitle||id} as any}
  initialReport={reportId?{report_id:reportId,title:instance.args.reportTitle||reportId} as any:undefined}
  onSaved={syncLocalReports} onReport={report=>instance.open("research-report",{researchId:id,researchTitle:title,
   reportId:report.report_id,reportTitle:report.title,localResearch:true,profileId:instance.args.profileId||"self"})}/>:<Spin tip={t("loading")}/>
  :error?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("empty")}/>:!detail||(reportId&&!selected)?<Spin tip={t("loading")}/>
  :reportId&&selected?<>
        {linkedResearch ? <Button type="link" onClick={() => openResearch(linkedResearch,selected.research?.title || selected.research_title || linkedResearch)}>{t("research.openLinkedResearch")}</Button> : null}
        {linkedResearch && selected.report_id && selected.owner_ref===principal && !selected.__hasLocal &&
         local.phase==="ready" && local.client && local.capabilities?.actions.includes("import_catalog_report") &&
         local.capabilities.profiles.some(item=>item.profile_id==="self") ? <Button loading={importingReport} onClick={()=>{
          const client=local.client!,profile=local.capabilities!.profiles.find(item=>item.profile_id==="self")!,snapshot=client.snapshot();
          if(pendingImport.current)return;pendingImport.current=true;setImportingReport(true);
          void client.importResearch(profile.profile_id,linkedResearch)
            .then(()=>client.importCatalogReport(profile.profile_id,linkedResearch,String(selected.report_id)))
            .then(()=>{if(client.isCurrent(snapshot)){notify({code:"research.report.imported",type:"success",message:t("localResearch.importReportDone")});refresh();syncLocalReports();}})
            .catch(()=>{if(client.isCurrent(snapshot))notify({code:"research.report.import.failed",type:"error",message:t("localResearch.importReportFailed")});})
            .finally(()=>{if(client.isCurrent(snapshot))pendingImport.current=false;setImportingReport(false);});
        }}>{t("localResearch.importReport")}</Button> : null}
        {linkedResearch && selected.report_id ? <Collapse className="tr-report-sharing" ghost items={[{key:"sharing",label:t("researchSharing.title"),children:<ResearchSharing key={`${linkedResearch}:${selected.report_id}`} target={{researchId:linkedResearch,reportId:String(selected.report_id)}} />}]} /> : null}
        {availableReportBranches.length ? <div className="tr-report-source-picker">
          <div className="tr-report-source-label"><span>{t("research.reportVersion")}</span>{selectedPublicationBranch ? <Tag>{t("report.readOnly")}</Tag> : null}</div>
          <Select
            aria-label={t("research.reportVersion")}
            value={selectedReportBranch?.publication_id}
            options={availableReportBranches.map((branch) => ({
              value: branch.publication_id,
              label: [branch.title || branch.branch_ref || branch.publication_id, branch.profile_ref].filter(Boolean).join(" · "),
            }))}
            onChange={setSelectedPublicationID}
          />
          {selectedReportBranch ? <ReportExport target={{...selected, ...selectedReportBranch, title:selected.title || selectedReportBranch.title}} /> : null}
        </div> : null}
        {selectedPublicationBranch?.publication_id
          ? <><ReportBranchReader key={`reader:${selectedPublicationBranch.publication_id}`} target={{...selected,...selectedPublicationBranch}} initialChapterID={readingChapter.publicationID === selectedPublicationBranch.publication_id ? readingChapter.chapterID : ""} onChapterChange={chapterID => setReadingChapter({publicationID:selectedPublicationBranch.publication_id || "",chapterID})} /><ReportMarkdown key={`markdown:${selectedPublicationBranch.publication_id}`} target={{...selected,...selectedPublicationBranch}} /></>
          : selectedReportBranch?.publication_id && ["client", "server_agent"].includes(String(selectedReportBranch.source_kind))
            ? <><ReportBranchReader key={selectedReportBranch.publication_id} target={{...selected,...selectedReportBranch}} /></>
            : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("research.noReadableVersion")} />}
      </>
  :editingResearch?<ResearchEdit research={detail} onCancel={()=>setEditingResearch(false)}
   onArchived={()=>{setEditingResearch(false);refresh();}} onSaved={value=>{setDetail(value);setEditingResearch(false);refresh();}}/>
  :<ResearchRelations research={detail} onSectionChange={setSection}
   overview={<><ResearchSummary value={detail}/>{detail.access?.can_manage?<div className="tr-inline-actions"><Button onClick={()=>setEditingResearch(true)}>{t("research.edit")}</Button></div>:null}</>}
   onReport={report=>instance.open("research-report",{researchId:id,researchTitle:title,reportId:String(report.report_id),reportTitle:String(report.title||report.report_id)})}
   onResearch={research=>openResearch(String(research.research_id),String(research.title||research.research_id))}/>;
 return <div className="tr-research-page" onPointerDownCapture={()=>assistantResearchContexts.activate(instance.id)} onFocusCapture={()=>assistantResearchContexts.activate(instance.id)}>
  <FunctionPage title={reportId?String(selected?.title||instance.args.reportTitle||reportId):title}
   actions={!instance.args.localResearch?<Button type="text" icon={<ReloadOutlined/>} aria-label={t("configuration.reload")} onClick={refresh}/>:undefined}>{content}</FunctionPage></div>;
}
function ResearchSummary({value}:{value:Row}):React.ReactElement {
 const {t}=useTranslation();
 return <PropertyGroups groups={[{key:"research",title:t("details"),items:[
  {key:"description",label:t("library.description"),value:value.description,wide:true},
  {key:"owner",label:t("library.owner"),value:value.owner_ref,render:ref=><ObjectReference value={{kind:"user",ref:String(ref),label:value.owner_alias||String(ref)}}/>},
  {key:"updated",label:t("jobs.updated"),value:value.updated_at,render:date=>formatDate(date as number|string,{dateStyle:"medium",timeStyle:"short"})},
  {key:"profile",label:t("research.profile"),value:value.profile_ref,render:ref=><ObjectReference value={{kind:"profile",ref:String(ref),profileKey:value.profile_key,owner:value.owner_ref}}/>},
 ]}]} />;
}
