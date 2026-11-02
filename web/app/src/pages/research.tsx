import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Collapse, Dropdown, Select, Spin, Tabs, Tag } from "antd";
import { DownOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { formatDate } from "../format.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { PropertyGroups } from "../components/property-groups.tsx";
import { ObjectReference } from "../components/object-reference.tsx";
import { ResearchCreate } from "../components/research-create.tsx";
import { useAuth } from "../auth.tsx";
import { usePageInstance } from "../page-instance.ts";
import { assistantResearchContexts } from "../assistant-research-context.ts";
import { ReportMarkdown } from "../components/report-markdown.tsx";
import { ReportExport } from "../components/report-export.tsx";
import { ReportBranchReader } from "../components/report-branch-reader.tsx";
import { ResearchEdit } from "../components/research-edit.tsx";
import { ResearchRelations } from "../components/research-relations.tsx";
import { ResearchSharing } from "../components/research-sharing.tsx";
import { LocalResearchCreate, LocalResearchDetail } from "../components/local-research-page.tsx";
import { useLocalResearchContext } from "../local-research-context.tsx";
import type { LocalReportWithResearch, LocalResearchPage } from "../local-research-bridge.ts";
import { notify } from "../notifications/core.ts";
import { linkedResearchID, reportBranches, reportRowID, researchRowID, selectReportBranch } from "../research-model.ts";
type Row = Record<string, any>;
export function ResearchPage(): React.ReactElement {
  const {session}=useAuth();
  const identity=session as (typeof session & {keycloak_issuer?:string;tr_identity_id?:string;keycloak_subject?:string});
  const identityKey=JSON.stringify([identity?.username,identity?.keycloak_issuer,identity?.tr_identity_id,identity?.keycloak_subject,identity?.visitor_login]);
  return <ResearchPageForSession key={identityKey} />;
}
function ResearchPageForSession(): React.ReactElement {
  const { t } = useTranslation();
  const { session, openAuth } = useAuth();
  const instance = usePageInstance();
  const local = useLocalResearchContext();
  const [localRows,setLocalRows]=useState<Row[]>([]);
  const [localDirectoryReady,setLocalDirectoryReady]=useState(false);
  const queuedServerResearch=useRef(new Set<string>());
  const [localRevision,setLocalRevision]=useState(0);
  const [creatingLocal,setCreatingLocal]=useState(false);
  const [importingReport,setImportingReport]=useState(false);
  const [localProfile,setLocalProfile]=useState<string | null>(null);
  const lastLocalError=useRef("");
  const missingReportDirectory=useRef(false);
  const localAttempt=useRef<{signature:string;id:string}|null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState("researches"), [rows, setRows] = useState<Row[]>([]);
  const [page, setPage] = useState(1), [size, setSize] = useState(20), [revision, setRevision] = useState(0);
  const syncLocalReports = local.requestSync;
  useEffect(() => { if (local.syncRevision) setRevision(value => value + 1); }, [local.syncRevision]);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null), [detail, setDetail] = useState<unknown>(null);
  const [detailPrincipal, setDetailPrincipal] = useState<string | null>(null);
  const [editingResearch, setEditingResearch] = useState(false);
  const [selectedPublicationID, setSelectedPublicationID] = useState("");
  const [readingChapter, setReadingChapter] = useState({publicationID:"",chapterID:""});
  const [researchLocation, setResearchLocation] = useState({id:"",section:"details"});
  const rowID = (row: Row, view = tab): string => view === "reports" ? reportRowID(row) : researchRowID(row);
  const selectedResearchID = tab === "researches" && selected ? researchRowID(selected) : "";
  const researchSection = researchLocation.id === selectedResearchID ? researchLocation.section : "details";
  const principal = session?.username || "";
  useEffect(() => { setResearchLocation(value => value.id === selectedResearchID ? value : {id:selectedResearchID,section:"details"}); }, [selectedResearchID]);
  useEffect(() => {
    const value = detail as Row | null;
    const allowed = !selected?.__local && instance.active !== false && principal && detailPrincipal === principal && selectedResearchID && value?.research_id === selectedResearchID && value?.access?.can_view === true;
    assistantResearchContexts.set(instance.id, allowed ? {
      researchId:selectedResearchID,title:String(value.title || selectedResearchID),section:researchSection,
    } : null);
  }, [detail,detailPrincipal,instance.active,instance.id,principal,researchSection,selectedResearchID,selected?.__local]);
  useEffect(() => () => assistantResearchContexts.set(instance.id, null), [instance.id]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    const endpoint = tab === "reports" ? "/api/research/reports" : "/api/research";
    void request(`${endpoint}?${new URLSearchParams({scope:"all"})}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setRows(data.researches || data.reports || data.items || []); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tab, revision]);
  useEffect(() => {
    const controller = new AbortController(); setDetail(null); setDetailPrincipal(null); setEditingResearch(false); if (!selected || selected.__local) return ()=>controller.abort();
    if (tab !== "reports") void request(`/api/research/${encodeURIComponent(researchRowID(selected))}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) { setDetail(data.research || data); setDetailPrincipal(principal); } }).catch((reason) => { if (!controller.signal.aborted) setDetail({ error: reason.message }); });
    return () => controller.abort();
  }, [selected, tab, principal]);
  useEffect(() => {
    let active=true;
    setLocalDirectoryReady(false);
    if(local.phase!=="ready" || !local.client || !local.capabilities || (tab==="reports" && !local.capabilities.actions.includes("list_profile_reports"))){setLocalRows([]);return()=>{active=false;};}
    const client=local.client, snapshot=client.snapshot(), profiles=local.capabilities.profiles;
    let nextProfile=0,total=0;
    const groups:Row[][]=Array.from({length:profiles.length},()=>[]);
    const loadProfile=async(item:typeof profiles[number])=>{
      const collected:Row[]=[]; let offset=0,expectedRevision:number|null=null;
      for(let page=0;page<50;page++){
        const result:LocalResearchPage|{reports:LocalReportWithResearch[];next_offset:number|null;revision:number}=tab==="researches" ? (local.capabilities!.actions.includes("list_researches") ? await client.listResearches(item.profile_id,{offset,limit:200,expectedRevision}) : await client.list(item.profile_id,{offset,limit:200})) : await client.listProfileReports(item.profile_id,{offset,limit:200,expectedRevision});
        if(!active || !client.isCurrent(snapshot))return [];
        const values="researches" in result ? result.researches : result.reports;
        total+=values.length;
        if(total>10000)throw new Error("local_research_too_many");
        collected.push(...values.map(value=>({...value,__local:true,owner_ref:principal,profile_id:item.profile_id})));
        if("revision" in result)expectedRevision=result.revision;
        if(result.next_offset===null)return collected;
        offset=result.next_offset;
      }
      throw new Error("local_research_too_many");
    };
    void Promise.all(Array.from({length:Math.min(4,profiles.length)},async()=>{
      while(active){const index=nextProfile++;if(index>=profiles.length)return;groups[index]=await loadProfile(profiles[index]);}
    })).then(()=>{if(active && client.isCurrent(snapshot)){setLocalRows(groups.flat());setLocalDirectoryReady(true);}}).catch(reason=>{if(active && client.isCurrent(snapshot)){setLocalRows([]);const code=reason instanceof Error?reason.message:"";notify({code:"research.local.load",type:"error",message:["local_research_too_many","local_research_listing_changed"].includes(code) ? t(`localResearch.errors.${code}`) : t("localResearch.errors.default")});}});
    return()=>{active=false;};
  },[tab,local.phase,local.client,local.capabilities,principal,revision,localRevision,t]);
  useEffect(()=>{
    const client=local.client,profile=local.capabilities?.profiles.find(item=>item.profile_id==="self");
    if(tab!=="researches"||!localDirectoryReady||local.phase!=="ready"||!client||!profile||
       !local.capabilities?.actions.includes("queue_researches"))return;
    const known=new Map(localRows.map(row=>[String(row.research_id||""),row]));
    const eligible=rows.filter(row=>row.owner_ref===principal&&row.is_owned===true&&row.access?.can_view===true)
      .map(row=>({id:String(row.research_id||""),version:Number(row.updated_at)}));
    const candidates=[...new Map(eligible.map(item=>[item.id,item])).values()]
      .filter(({id,version})=>/^research:v1:[A-Za-z0-9_-]{24,128}$/.test(id)&&
        (!known.has(id)||(Number.isFinite(version)&&version>Number(known.get(id)?.updated_at)))&&
        !queuedServerResearch.current.has(`${id}:${version}`));
    if(!candidates.length)return;
    let active=true;const snapshot=client.snapshot();
    void (async()=>{
      for(let offset=0;offset<candidates.length&&active;offset+=100){
        const batch=candidates.slice(offset,offset+100);
        try{await client.queueResearches(profile.profile_id,batch.map(item=>item.id));if(!active||!client.isCurrent(snapshot))return;batch.forEach(item=>queuedServerResearch.current.add(`${item.id}:${item.version}`));syncLocalReports();}
        catch{if(active&&client.isCurrent(snapshot))notify({code:"research.import.pending",type:"warning",message:t("research.importPending")});return;}
      }
    })();
    return()=>{active=false;};
  },[tab,localDirectoryReady,local.phase,local.client,local.capabilities,localRows,rows,principal,syncLocalReports,t]);
  useEffect(()=>{
    if(local.phase!=="unavailable"){lastLocalError.current="";return;}
    const key=`${local.key}:${local.code}`;
    if(lastLocalError.current!==key){lastLocalError.current=key;notify({code:"research.local.unavailable",type:"warning",message:t(`localResearch.errors.${local.code}`,{defaultValue:t("localResearch.errors.default")})});}
  },[local.phase,local.key,local.code,t]);
  useEffect(()=>{
    if(local.phase!=="ready" || local.capabilities?.actions.includes("list_profile_reports")){missingReportDirectory.current=false;return;}
    if(tab==="reports" && !missingReportDirectory.current){
      missingReportDirectory.current=true;
      notify({code:"research.local.reportDirectory.unsupported",type:"warning",message:t("localResearch.reportDirectoryUnavailable")});
    }
  },[tab,local.phase,local.capabilities,t]);
  useEffect(()=>{if(error)notify({code:"research.server.load",type:"error",message:error});},[error]);
  const filtered = useMemo(() => {
    if(tab!=="researches")return [...localRows,...rows];
    const remaining=new Map(localRows.map(row=>[row.research_id,row]));
    const server=rows.map(row=>{
      const id=researchRowID(row),localRow=remaining.get(id);
      if(!localRow || String(row.owner_ref || row.owner || "")!==principal)return row;
      remaining.delete(id);
      return {...row,__hasLocal:true,profile_id:row.profile_id || localRow.profile_id};
    });
    return [...remaining.values(),...server];
  }, [rows,localRows,tab,principal]);
  const availableReportBranches = tab === "reports" && selected ? reportBranches(selected) : [];
  const selectedReportBranch = tab === "reports" && selected ? selectReportBranch(selected, selectedPublicationID) : undefined;
  const selectedPublicationBranch = selectedReportBranch?.source_kind === "publication" ? selectedReportBranch : undefined;
  const linkedResearch = selected ? linkedResearchID(selected) : "";
  const openResearch = (id:string, title:string): void => {setTab("researches");setRows([]);setPage(1);setSelected({research_id:id,title});setSelectedPublicationID("");setEditingResearch(false);};
  const owner = (row:Row): React.ReactNode => row.owner_ref || row.owner ? <ObjectReference value={{kind:"user",ref:row.owner_ref || row.owner,label:row.owner_alias || row.owner_ref || row.owner}} /> : "—";
  const profile = (row:Row): React.ReactNode => {
    const ref = row.profile_ref || row.profile_id || row.selected_branch?.profile_ref;
    if(ref && row.__local){const item=local.capabilities?.profiles.find(value=>value.profile_id===ref);return <button type="button" className="tr-table-link" onClick={()=>setLocalProfile(String(ref))}>{item?.display_name || String(ref)}</button>;}
    return ref ? <ObjectReference value={{kind:"profile",ref:String(ref),profileKey:row.profile_key,owner:row.owner_ref || row.owner}} /> : "—";
  };
  const researchLink = (row:Row): React.ReactNode => {
    const id = linkedResearchID(row), title = String(row.research?.title || row.research_title || id);
    return id ? <button type="button" className="tr-table-link" onClick={() => {
      if(row.__local && row.research){setTab("researches");setRows([]);setPage(1);setSelected({...row.research,__local:true,owner_ref:principal});}
      else openResearch(id,title);
    }}>{title}</button> : "—";
  };
  const activateServer=():void=>{assistantResearchContexts.activate(instance.id);};
  const canCreateLocal=local.phase==="ready" && local.capabilities?.actions.includes("create");
  return <div className="tr-research-page" onPointerDownCapture={activateServer} onFocusCapture={activateServer}><FunctionPage title={t("nav.research")} actions={<>{tab === "researches" ? canCreateLocal && session ? <Dropdown trigger={["click"]} menu={{items:[{key:"local",label:t("localResearch.local")},{key:"server",label:t("localResearch.server")}],onClick:({key})=>key==="local" ? setCreatingLocal(true) : setCreating(true)}}><Button type="primary">{t("research.create")} <DownOutlined /></Button></Dropdown> : <Button type="primary" onClick={() => session ? setCreating(true) : openAuth("login")}>{t("research.create")}</Button> : null}<Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision((value) => value + 1)} /></>}>
    <Tabs activeKey={tab} onChange={(value) => { setTab(value); setRows([]); setPage(1); setSelected(null); setSelectedPublicationID(""); }} items={[{ key: "researches", label: t("research.tabResearches") }, { key: "reports", label: t("research.tabReports") }]} />
    <div className="tr-research-table"><TRDataTable clientFiltering rows={filtered} rowKey={(row) => `${row.__local ? "local" : "server"}:${rowID(row)}`} loading={loading} pagination={{ page, pageSize: size, total: filtered.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("editor.name"), key: "title", render: (_, row) => row.__local && tab === "reports" && !local.capabilities?.actions.includes("get_report") ? row.title : <button className="tr-table-link" onClick={() => { setSelected(row); setSelectedPublicationID(tab === "reports" ? selectReportBranch(row)?.publication_id || "" : "");  }}>{row.title || rowID(row)}</button> },
      ...(tab === "reports" ? [{title:t("research.linkedResearch"),key:"research",render:(_:unknown,row:Row) => researchLink(row)}] : []),
      {title:t("research.profile"),key:"profile",className:"tr-research-profile-column",filters:Array.from(new Set(filtered.map(row=>String(row.profile_ref || row.profile_id || row.selected_branch?.profile_ref || "")).filter(Boolean))).map(value=>({text:value,value})),onFilter:(value:React.Key | boolean,row:Row)=>String(row.profile_ref || row.profile_id || row.selected_branch?.profile_ref || "")===String(value),render:(_:unknown,row:Row) => profile(row)},
      {title:t("localResearch.location"),key:"location",filters:[{text:t("localResearch.local"),value:"local"},{text:t("localResearch.server"),value:"server"}],onFilter:(value:React.Key | boolean,row:Row)=>value==="local" ? !!(row.__local || row.__hasLocal) : !row.__local,render:(_:unknown,row:Row)=>row.__hasLocal ? `${t("localResearch.local")} / ${t("localResearch.server")}` : t(row.__local ? "localResearch.local" : "localResearch.server")},
      ...([
        { title: t("library.owner"), key: "owner", filters:Array.from(new Set(filtered.map(row=>String(row.owner_ref || row.owner || "")).filter(Boolean))).map(value=>({text:value,value})), onFilter:(value:React.Key | boolean,row:Row)=>String(row.owner_ref || row.owner || "")===String(value), render: (_:unknown, row:Row) => owner(row) },
        { title: t("jobs.updated"), dataIndex: "updated_at", render: (value:number|string) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
      ]),
    ]} /></div>
    {creatingLocal && local.client && local.capabilities?.profiles.length ? <LocalResearchCreate client={local.client} profiles={local.capabilities.profiles} initialProfile={local.capabilities.profiles[0].profile_id} operation={localAttempt} onClose={()=>setCreatingLocal(false)} onCreated={()=>{localAttempt.current=null;setCreatingLocal(false);setRevision(value=>value+1);}} />:null}
    {localProfile ? <DetailsPanel title={t("research.profile")} onClose={()=>setLocalProfile(null)} width={520}><PropertyGroups groups={[{key:"profile",title:t("research.profile"),items:[{key:"name",label:t("editor.name"),value:local.capabilities?.profiles.find(value=>value.profile_id===localProfile)?.display_name || localProfile},{key:"id",label:t("objectReference.reference"),value:localProfile}]}]} /></DetailsPanel>:null}
    {creating ? <ResearchCreate onClose={() => setCreating(false)} onCreated={(value) => {
      setCreating(false);setSelected(value);setRevision(current=>current+1);
      const client=local.client,profile=local.capabilities?.profiles.find(item=>item.profile_id==="self");
      if(local.phase==="ready" && client && profile){
        if(!local.capabilities?.actions.includes("import_research")){notify({code:"research.import.pending",type:"warning",message:t("research.importPending")});return;}
        const snapshot=client.snapshot();
        void client.importResearch(profile.profile_id,String(value.research_id||""))
          .then(()=>{if(client.isCurrent(snapshot))setLocalRevision(current=>current+1);})
          .catch(()=>{if(client.isCurrent(snapshot)){notify({code:"research.import.pending",type:"warning",message:t("research.importPending")});syncLocalReports();}});
      }
    }} /> : null}
    {selected?.__local && local.client && local.capabilities ? <LocalResearchDetail key={`${selected.profile_id}:${rowID(selected)}`} client={local.client} capabilities={local.capabilities} item={(tab === "reports" ? selected.research : selected) as any} initialReport={tab === "reports" ? selected as any : undefined} onSaved={()=>{setLocalRevision(value=>value+1);syncLocalReports();}} onClose={()=>setSelected(null)} /> : null}
    {selected && !selected.__local ? <DetailsPanel title={selected.title || rowID(selected)} onClose={() => { setSelected(null); setSelectedPublicationID(""); }}>
      {tab === "reports" ? <>
        {linkedResearch ? <Button type="link" onClick={() => openResearch(linkedResearch,selected.research?.title || selected.research_title || linkedResearch)}>{t("research.openLinkedResearch")}</Button> : null}
        {linkedResearch && selected.report_id && selected.owner_ref===principal && !selected.__hasLocal &&
         local.phase==="ready" && local.client && local.capabilities?.actions.includes("import_catalog_report") &&
         local.capabilities.profiles.some(item=>item.profile_id==="self") ? <Button loading={importingReport} onClick={()=>{
          const client=local.client!,profile=local.capabilities!.profiles.find(item=>item.profile_id==="self")!,snapshot=client.snapshot();
          setImportingReport(true);
          void client.importResearch(profile.profile_id,linkedResearch)
            .then(()=>client.importCatalogReport(profile.profile_id,linkedResearch,String(selected.report_id)))
            .then(()=>{if(client.isCurrent(snapshot)){notify({code:"research.report.imported",type:"success",message:t("localResearch.importReportDone")});setLocalRevision(value=>value+1);syncLocalReports();}})
            .catch(()=>{if(client.isCurrent(snapshot))notify({code:"research.report.import.failed",type:"error",message:t("localResearch.importReportFailed")});})
            .finally(()=>{if(client.isCurrent(snapshot))setImportingReport(false);});
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
            ? <><Alert type="info" showIcon message={t("report.branchReadOnly")} /><ReportBranchReader key={selectedReportBranch.publication_id} target={{...selected,...selectedReportBranch}} /></>
            : <Alert type="info" showIcon message={t("research.reportVersionUnavailable")} description={selectedReportBranch ? t(`research.reportSources.${selectedReportBranch.source_kind || "unknown"}`) : selected.build_source === "workspace" ? t("research.reportSources.workspace") : undefined} />}
      </>
        : editingResearch ? <ResearchEdit research={selected as Row} onCancel={() => setEditingResearch(false)} onArchived={() => { setSelected(null); setEditingResearch(false); setRevision((value) => value + 1); }} onSaved={(value) => { setSelected({ ...selected, ...value }); setDetail(value); setEditingResearch(false); setRevision((revision) => revision + 1); }} />
        : detail && !(detail as Row).error ? <ResearchRelations key={researchRowID(selected)} research={detail as Row} onSectionChange={section => setResearchLocation({id:selectedResearchID,section})} overview={<><ResearchSummary value={detail as Row} />{(detail as Row).access?.can_manage ? <div className="tr-inline-actions"><Button onClick={() => setEditingResearch(true)}>{t("research.edit")}</Button></div> : null}</>} onReport={(report) => { setTab("reports"); setRows([]); setPage(1); setSelected(report); setSelectedPublicationID(selectReportBranch(report)?.publication_id || ""); }} onResearch={(research) => { setTab("researches"); setSelected(research); setEditingResearch(false); }} /> : <ResearchSummary value={detail as Row | null} />}
    </DetailsPanel> : null}
  </FunctionPage></div>;
}


function ResearchSummary({value}:{value:Row|null}):React.ReactElement {
  const {t}=useTranslation();
  if(!value)return <Spin tip={t("loading")} />;
  if(value.error)return <Alert type="error" showIcon message={String(value.error)} />;
  return <PropertyGroups groups={[{key:"research",title:t("research.tabResearches"),items:[
    {key:"title",label:t("editor.name"),value:value.title},
    {key:"description",label:t("library.description"),value:value.description,wide:true},
    {key:"owner",label:t("library.owner"),value:value.owner_ref,render:ref=><ObjectReference value={{kind:"user",ref:String(ref),label:value.owner_alias||String(ref)}} />},
    {key:"updated",label:t("jobs.updated"),value:value.updated_at,render:value=>formatDate(value as number|string,{dateStyle:"medium",timeStyle:"short"})},
    {key:"profile",label:t("research.profile"),value:value.profile_ref,render:ref=><ObjectReference value={{kind:"profile",ref:String(ref),profileKey:value.profile_key,owner:value.owner_ref}} />},
  ]}]} />;
}
