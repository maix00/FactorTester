import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Spin, Tabs, Tag } from "antd";
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
  const id = (row: Row): string => row.research_id || row.publication_id || row.report_id;
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void request(tab === "reports" ? "/api/research/reports?scope=all" : "/api/research?scope=all", { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setRows(data.researches || data.reports || data.items || []); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tab, revision]);
  useEffect(() => {
    const controller = new AbortController(); setDetail(null); setEditingResearch(false); if (!selected) return;
    if (tab !== "reports") void request(`/api/research/${encodeURIComponent(id(selected))}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setDetail(data.research || data); }).catch((reason) => { if (!controller.signal.aborted) setDetail({ error: reason.message }); });
    return () => controller.abort();
  }, [selected, tab]);
  const filtered = useMemo(() => rows.filter((row) => !query || `${row.title || ""} ${row.owner_ref || row.owner || ""}`.toLowerCase().includes(query.toLowerCase())), [rows, query]);
  return <FunctionPage title={t("nav.research")} actions={<>{tab === "researches" ? <Button type="primary" onClick={() => session ? setCreating(true) : openAuth("login")}>{t("research.create")}</Button> : null}<Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision((value) => value + 1)} /></>}>
    <Tabs activeKey={tab} onChange={(value) => { setTab(value); setRows([]); setPage(1); setSelected(null); setEditor(false); }} items={[{ key: "researches", label: t("research.tabResearches") }, { key: "reports", label: t("research.tabReports") }]} />
    <div className="tr-library-filters"><Input.Search allowClear aria-label={t("library.search")} placeholder={t("library.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></div>
    <TRDataTable rows={filtered.slice((page - 1) * size, page * size)} rowKey={id} loading={loading} error={error} pagination={{ page, pageSize: size, total: filtered.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("editor.name"), key: "title", render: (_, row) => <button className="tr-table-link" onClick={() => { setSelected(row); setEditor(false); }}>{row.title || id(row)}</button> },
      { title: t("library.owner"), key: "owner", responsive: ["md"], render: (_, row) => row.owner_alias || row.owner_ref || row.owner || "—" },
      { title: t("library.visibility"), dataIndex: "visibility", responsive: ["md"], render: (value) => value ? <Tag>{t(`research.visibility.${value}`, { defaultValue: value })}</Tag> : "—" },
      { title: t("jobs.updated"), dataIndex: "updated_at", render: (value) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
    ]} />
    {creating ? <ResearchCreate onClose={() => setCreating(false)} onCreated={(value) => { setCreating(false); setSelected(value); setEditor(false); setRevision(revision => revision + 1); }} /> : null}
    {selected ? <DetailsPanel title={selected.title || id(selected)} onClose={() => { setSelected(null); setEditor(false); }}>
      {tab === "reports" ? <><ReportEditor publicationID={id(selected)} /><ReportMarkdown key={id(selected)} publicationID={id(selected)} /></>
        : editingResearch ? <ResearchEdit research={selected as Row} onCancel={() => setEditingResearch(false)} onArchived={() => { setSelected(null); setEditingResearch(false); setRevision((value) => value + 1); }} onSaved={(value) => { setSelected({ ...selected, ...value }); setDetail(value); setEditingResearch(false); setRevision((revision) => revision + 1); }} />
        : editor ? <iframe className="tr-artifact-frame" title={selected.title || id(selected)} src={`/researches/${encodeURIComponent(id(selected))}?presentation=embedded`} /> : <><ResearchSummary value={detail as Row | null} /><div className="tr-inline-actions"><Button onClick={() => setEditingResearch(true)}>{t("research.edit")}</Button><Button onClick={() => setEditor(true)}>{t("research.openEditor")}</Button></div></>}
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
