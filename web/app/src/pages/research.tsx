import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Select, Spin, Tabs, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { formatDate } from "../format.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { ResultView } from "../components/result-view.tsx";
import { PropertyGroups } from "../components/property-groups.tsx";
import { ObjectReference } from "../components/object-reference.tsx";
import { ResearchCreate } from "../components/research-create.tsx";
import { useAuth } from "../auth.tsx";
import { ReportEditor } from "../components/report-editor.tsx";
import { ReportMarkdown } from "../components/report-markdown.tsx";
import { ReportExport } from "../components/report-export.tsx";
import { ReportBranchReader } from "../components/report-branch-reader.tsx";
import { ResearchEdit } from "../components/research-edit.tsx";
import { ResearchRelations } from "../components/research-relations.tsx";
import { linkedResearchID, reportBranches, reportRowID, researchRowID, selectReportBranch } from "../research-model.ts";
type Row = Record<string, any>;
export function ResearchPage(): React.ReactElement {
  const { t } = useTranslation();
  const { session, openAuth } = useAuth();
  const compact = useCompactLayout();
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState("researches"), [rows, setRows] = useState<Row[]>([]), [query, setQuery] = useState("");
  const [scope,setScope] = useState("all");
  const [page, setPage] = useState(1), [size, setSize] = useState(20), [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null), [detail, setDetail] = useState<unknown>(null), [editor, setEditor] = useState(false);
  const [editingResearch, setEditingResearch] = useState(false);
  const [selectedPublicationID, setSelectedPublicationID] = useState("");
  const [reportRevision, setReportRevision] = useState(0);
  const [readingChapter, setReadingChapter] = useState({publicationID:"",chapterID:""});
  const rowID = (row: Row, view = tab): string => view === "reports" ? reportRowID(row) : researchRowID(row);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    const endpoint = tab === "reports" ? "/api/research/reports" : "/api/research";
    void request(`${endpoint}?${new URLSearchParams({scope})}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setRows(data.researches || data.reports || data.items || []); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tab, scope, revision]);
  useEffect(() => {
    const controller = new AbortController(); setDetail(null); setEditingResearch(false); if (!selected) return;
    if (tab !== "reports") void request(`/api/research/${encodeURIComponent(researchRowID(selected))}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setDetail(data.research || data); }).catch((reason) => { if (!controller.signal.aborted) setDetail({ error: reason.message }); });
    return () => controller.abort();
  }, [selected, tab]);
  const filtered = useMemo(() => rows.filter((row) => !query || `${row.title || ""} ${row.owner_ref || row.owner || ""} ${row.research?.title || row.research_title || ""} ${row.profile_ref || row.profile_id || ""}`.toLowerCase().includes(query.toLowerCase())), [rows, query]);
  const availableReportBranches = tab === "reports" && selected ? reportBranches(selected) : [];
  const selectedReportBranch = tab === "reports" && selected ? selectReportBranch(selected, selectedPublicationID) : undefined;
  const selectedPublicationBranch = selectedReportBranch?.source_kind === "publication" ? selectedReportBranch : undefined;
  const linkedResearch = selected ? linkedResearchID(selected) : "";
  const openResearch = (id:string, title:string): void => {setTab("researches");setRows([]);setPage(1);setSelected({research_id:id,title});setSelectedPublicationID("");setEditor(false);setEditingResearch(false);};
  const owner = (row:Row): React.ReactNode => row.owner_ref || row.owner ? <ObjectReference value={{kind:"user",ref:row.owner_ref || row.owner,label:row.owner_alias || row.owner_ref || row.owner}} /> : "—";
  const profile = (row:Row): React.ReactNode => {
    const ref = row.profile_ref || row.profile_id || row.selected_branch?.profile_ref;
    return ref ? <ObjectReference value={{kind:"profile",ref:String(ref),profileKey:row.profile_key,owner:row.owner_ref || row.owner}} /> : "—";
  };
  const researchLink = (row:Row): React.ReactNode => {
    const id = linkedResearchID(row), title = String(row.research?.title || row.research_title || id);
    return id ? <button type="button" className="tr-table-link" onClick={() => openResearch(id,title)}>{title}</button> : "—";
  };
  const mobileMeta = (label:string, value:React.ReactNode):React.ReactElement => <span className="tr-research-mobile-reference"><span>{label}</span><span>{value}</span></span>;
  return <FunctionPage title={t("nav.research")} actions={<>{tab === "researches" ? <Button type="primary" onClick={() => session ? setCreating(true) : openAuth("login")}>{t("research.create")}</Button> : null}<Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision((value) => value + 1)} /></>}>
    <Tabs activeKey={tab} onChange={(value) => { setTab(value); setRows([]); setPage(1); setSelected(null); setSelectedPublicationID(""); setEditor(false); }} items={[{ key: "researches", label: t("research.tabResearches") }, { key: "reports", label: t("research.tabReports") }]} />
    <div className="tr-library-filters"><Select aria-label={t("research.scope")} value={scope} onChange={value => {setScope(value);setRows([]);setPage(1);}} options={["all","mine","subordinates","shared"].map(value => ({value,label:t(`research.scopes.${value}`)}))} /><Input.Search allowClear aria-label={t("library.search")} placeholder={t("library.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></div>
    <div className="tr-research-table"><TRDataTable rows={filtered.slice((page - 1) * size, page * size)} rowKey={(row) => rowID(row)} loading={loading} error={error} pagination={{ page, pageSize: size, total: filtered.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("editor.name"), key: "title", render: (_, row) => <div><button className="tr-table-link" onClick={() => { setSelected(row); setSelectedPublicationID(tab === "reports" ? selectReportBranch(row)?.publication_id || "" : ""); setEditor(false); }}>{row.title || rowID(row)}</button>{compact ? <div className="tr-research-mobile-meta">{row.owner_ref || row.owner ? mobileMeta(t("library.owner"),owner(row)) : null}{tab === "reports" && (row.profile_ref || row.profile_id || row.selected_branch?.profile_ref) ? mobileMeta(t("research.profile"),profile(row)) : null}{tab === "reports" && linkedResearchID(row) ? mobileMeta(t("research.linkedResearch"),researchLink(row)) : null}{row.visibility ? mobileMeta(t("library.visibility"),t(`research.visibility.${row.visibility}`, { defaultValue: row.visibility })) : null}{row.updated_at ? mobileMeta(t("jobs.updated"),formatDate(row.updated_at, { dateStyle: "medium", timeStyle: "short" })) : null}</div> : null}</div> },
      ...(!compact && tab === "reports" ? [{title:t("research.linkedResearch"),key:"research",render:(_:unknown,row:Row) => researchLink(row)},{title:t("research.profile"),key:"profile",render:(_:unknown,row:Row) => profile(row)}] : []),
      ...(!compact ? [
        { title: t("library.owner"), key: "owner", render: (_:unknown, row:Row) => owner(row) },
        { title: t("library.visibility"), dataIndex: "visibility", render: (value:string) => value ? <Tag>{t(`research.visibility.${value}`, { defaultValue: value })}</Tag> : "—" },
        { title: t("jobs.updated"), dataIndex: "updated_at", render: (value:number|string) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
      ] : []),
    ]} /></div>
    {creating ? <ResearchCreate onClose={() => setCreating(false)} onCreated={(value) => { setCreating(false); setSelected(value); setEditor(false); setRevision(revision => revision + 1); }} /> : null}
    {selected ? <DetailsPanel title={selected.title || rowID(selected)} onClose={() => { setSelected(null); setSelectedPublicationID(""); setEditor(false); }}>
      {tab === "reports" ? <>
        {linkedResearch ? <Button type="link" onClick={() => openResearch(linkedResearch,selected.research?.title || selected.research_title || linkedResearch)}>{t("research.openLinkedResearch")}</Button> : null}
        {availableReportBranches.length ? <div className="tr-report-source-picker">
          <span>{t("research.reportVersion")}</span>
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
          ? <><ReportBranchReader key={`reader:${selectedPublicationBranch.publication_id}:${reportRevision}`} target={{...selected,...selectedPublicationBranch}} initialChapterID={readingChapter.publicationID === selectedPublicationBranch.publication_id ? readingChapter.chapterID : ""} onChapterChange={chapterID => setReadingChapter({publicationID:selectedPublicationBranch.publication_id || "",chapterID})} /><ReportEditor key={`editor:${selectedPublicationBranch.publication_id}`} publicationID={selectedPublicationBranch.publication_id} onUpdated={() => setReportRevision(value => value + 1)} /><ReportMarkdown key={`markdown:${selectedPublicationBranch.publication_id}:${reportRevision}`} publicationID={selectedPublicationBranch.publication_id} /></>
          : selectedReportBranch?.publication_id && ["client", "server_agent"].includes(String(selectedReportBranch.source_kind))
            ? <><Alert type="info" showIcon message={t("report.branchReadOnly")} /><ReportBranchReader key={selectedReportBranch.publication_id} target={{...selected,...selectedReportBranch}} /></>
            : <Alert type="info" showIcon message={t("research.reportVersionUnavailable")} description={selectedReportBranch ? t(`research.reportSources.${selectedReportBranch.source_kind || "unknown"}`) : selected.build_source === "workspace" ? t("research.reportSources.workspace") : undefined} />}
      </>
        : editingResearch ? <ResearchEdit research={selected as Row} onCancel={() => setEditingResearch(false)} onArchived={() => { setSelected(null); setEditingResearch(false); setRevision((value) => value + 1); }} onSaved={(value) => { setSelected({ ...selected, ...value }); setDetail(value); setEditingResearch(false); setRevision((revision) => revision + 1); }} />
        : editor ? <><Button onClick={() => setEditor(false)}>{t("research.backToSummary")}</Button><iframe className="tr-artifact-frame" title={selected.title || rowID(selected)} src={`/researches/${encodeURIComponent(researchRowID(selected))}?presentation=embedded`} /></> : detail && !(detail as Row).error ? <ResearchRelations key={researchRowID(selected)} research={detail as Row} overview={<><ResearchSummary value={detail as Row} /><div className="tr-inline-actions">{(detail as Row).access?.can_manage ? <Button onClick={() => setEditingResearch(true)}>{t("research.edit")}</Button> : null}<Button onClick={() => setEditor(true)}>{t("research.openEditor")}</Button></div></>} onReport={(report) => { setTab("reports"); setRows([]); setPage(1); setSelected(report); setSelectedPublicationID(selectReportBranch(report)?.publication_id || ""); }} onResearch={(research) => { setTab("researches"); setSelected(research); setEditingResearch(false); setEditor(false); }} /> : <ResearchSummary value={detail as Row | null} />}
    </DetailsPanel> : null}
  </FunctionPage>;
}


function ResearchSummary({value}:{value:Row|null}):React.ReactElement {
  const {t}=useTranslation();
  if(!value)return <Spin tip={t("loading")} />;
  if(value.error)return <Alert type="error" showIcon message={String(value.error)} />;
  return <><PropertyGroups groups={[{key:"research",title:t("research.tabResearches"),items:[
    {key:"title",label:t("editor.name"),value:value.title},
    {key:"description",label:t("library.description"),value:value.description,wide:true},
    {key:"owner",label:t("library.owner"),value:value.owner_ref,render:ref=><ObjectReference value={{kind:"user",ref:String(ref),label:value.owner_alias||String(ref)}} />},
    {key:"visibility",label:t("library.visibility"),value:value.visibility,render:value=>t(`research.visibility.${value}`,{defaultValue:String(value)})},
    {key:"updated",label:t("jobs.updated"),value:value.updated_at,render:value=>formatDate(value as number|string,{dateStyle:"medium",timeStyle:"short"})},
    {key:"profile",label:t("research.profile"),value:value.profile_ref,render:ref=><ObjectReference value={{kind:"profile",ref:String(ref),profileKey:value.profile_key,owner:value.owner_ref}} />},
  ]}]} /><details><summary>{t("details")}</summary><ResultView value={value}/></details></>;
}
