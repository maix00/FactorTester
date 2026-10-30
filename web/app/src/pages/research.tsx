import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Select, Spin, Tabs, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { formatDate } from "../format.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { ResultView } from "../components/result-view.tsx";
import { PropertyGroups } from "../components/property-groups.tsx";
import { ResearchCreate } from "../components/research-create.tsx";
import { useAuth } from "../auth.tsx";
import { ReportEditor } from "../components/report-editor.tsx";
import { ReportMarkdown } from "../components/report-markdown.tsx";
import { ResearchEdit } from "../components/research-edit.tsx";
import { linkedResearchID, reportBranches, reportRowID, researchRowID, selectReportBranch } from "../research-model.ts";
type Row = Record<string, any>;
export function ResearchPage(): React.ReactElement {
  const { t } = useTranslation();
  const { session, openAuth } = useAuth();
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState("researches"), [rows, setRows] = useState<Row[]>([]), [query, setQuery] = useState("");
  const [page, setPage] = useState(1), [size, setSize] = useState(20), [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null), [detail, setDetail] = useState<unknown>(null), [editor, setEditor] = useState(false);
  const [editingResearch, setEditingResearch] = useState(false);
  const [selectedPublicationID, setSelectedPublicationID] = useState("");
  const rowID = (row: Row, view = tab): string => view === "reports" ? reportRowID(row) : researchRowID(row);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void request(tab === "reports" ? "/api/research/reports?scope=all" : "/api/research?scope=all", { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setRows(data.researches || data.reports || data.items || []); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tab, revision]);
  useEffect(() => {
    const controller = new AbortController(); setDetail(null); setEditingResearch(false); if (!selected) return;
    if (tab !== "reports") void request(`/api/research/${encodeURIComponent(researchRowID(selected))}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setDetail(data.research || data); }).catch((reason) => { if (!controller.signal.aborted) setDetail({ error: reason.message }); });
    return () => controller.abort();
  }, [selected, tab]);
  const filtered = useMemo(() => rows.filter((row) => !query || `${row.title || ""} ${row.owner_ref || row.owner || ""}`.toLowerCase().includes(query.toLowerCase())), [rows, query]);
  const availableReportBranches = tab === "reports" && selected ? reportBranches(selected) : [];
  const selectedReportBranch = tab === "reports" && selected ? selectReportBranch(selected, selectedPublicationID) : undefined;
  const selectedPublicationBranch = selectedReportBranch?.source_kind === "publication" ? selectedReportBranch : undefined;
  const linkedResearch = selected ? linkedResearchID(selected) : "";
  return <FunctionPage title={t("nav.research")} actions={<>{tab === "researches" ? <Button type="primary" onClick={() => session ? setCreating(true) : openAuth("login")}>{t("research.create")}</Button> : null}<Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision((value) => value + 1)} /></>}>
    <Tabs activeKey={tab} onChange={(value) => { setTab(value); setRows([]); setPage(1); setSelected(null); setSelectedPublicationID(""); setEditor(false); }} items={[{ key: "researches", label: t("research.tabResearches") }, { key: "reports", label: t("research.tabReports") }]} />
    <div className="tr-library-filters"><Input.Search allowClear aria-label={t("library.search")} placeholder={t("library.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></div>
    <TRDataTable rows={filtered.slice((page - 1) * size, page * size)} rowKey={(row) => rowID(row)} loading={loading} error={error} pagination={{ page, pageSize: size, total: filtered.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("editor.name"), key: "title", render: (_, row) => <button className="tr-table-link" onClick={() => { setSelected(row); setSelectedPublicationID(tab === "reports" ? selectReportBranch(row)?.publication_id || "" : ""); setEditor(false); }}>{row.title || rowID(row)}</button> },
      { title: t("library.owner"), key: "owner", responsive: ["md"], render: (_, row) => row.owner_alias || row.owner_ref || row.owner || "—" },
      { title: t("library.visibility"), dataIndex: "visibility", responsive: ["md"], render: (value) => value ? <Tag>{t(`research.visibility.${value}`, { defaultValue: value })}</Tag> : "—" },
      { title: t("jobs.updated"), dataIndex: "updated_at", render: (value) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
    ]} />
    {creating ? <ResearchCreate onClose={() => setCreating(false)} onCreated={(value) => { setCreating(false); setSelected(value); setEditor(false); setRevision(revision => revision + 1); }} /> : null}
    {selected ? <DetailsPanel title={selected.title || rowID(selected)} onClose={() => { setSelected(null); setSelectedPublicationID(""); setEditor(false); }}>
      {tab === "reports" ? <>
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
        </div> : null}
        {selectedPublicationBranch?.publication_id
          ? <><ReportEditor key={selectedPublicationBranch.publication_id} publicationID={selectedPublicationBranch.publication_id} /><ReportMarkdown key={selectedPublicationBranch.publication_id} publicationID={selectedPublicationBranch.publication_id} /></>
          : <Alert type="info" showIcon message={t("research.reportVersionUnavailable")} description={selectedReportBranch ? t(`research.reportSources.${selectedReportBranch.source_kind || "unknown"}`) : selected.build_source === "workspace" ? t("research.reportSources.workspace") : undefined} action={linkedResearch ? <Button type="link" onClick={() => { setTab("researches"); setRows([]); setPage(1); setSelected({ research_id: linkedResearch, title: selected.research?.title || selected.title }); setSelectedPublicationID(""); setEditor(false); setEditingResearch(false); }}>{t("research.openLinkedResearch")}</Button> : undefined} />}
      </>
        : editingResearch ? <ResearchEdit research={selected as Row} onCancel={() => setEditingResearch(false)} onArchived={() => { setSelected(null); setEditingResearch(false); setRevision((value) => value + 1); }} onSaved={(value) => { setSelected({ ...selected, ...value }); setDetail(value); setEditingResearch(false); setRevision((revision) => revision + 1); }} />
        : editor ? <><Button onClick={() => setEditor(false)}>{t("research.backToSummary")}</Button><iframe className="tr-artifact-frame" title={selected.title || rowID(selected)} src={`/researches/${encodeURIComponent(researchRowID(selected))}?presentation=embedded`} /></> : <><ResearchSummary value={detail as Row | null} /><div className="tr-inline-actions"><Button onClick={() => setEditingResearch(true)}>{t("research.edit")}</Button><Button onClick={() => setEditor(true)}>{t("research.openEditor")}</Button></div></>}
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
    {key:"owner",label:t("library.owner"),value:value.owner_alias||value.owner_ref},
    {key:"visibility",label:t("library.visibility"),value:value.visibility,render:value=>t(`research.visibility.${value}`,{defaultValue:String(value)})},
    {key:"updated",label:t("jobs.updated"),value:value.updated_at,render:value=>formatDate(value as number|string,{dateStyle:"medium",timeStyle:"short"})},
    {key:"profile",label:t("research.profile"),value:value.profile_ref},
  ]}]} /><details><summary>{t("details")}</summary><ResultView value={value}/></details></>;
}
