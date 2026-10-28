import React, { useEffect, useMemo, useState } from "react";
import { Button, Input, Tabs, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { formatDate } from "../format.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { ResultView } from "../components/result-view.tsx";
import { ResearchCreate } from "../components/research-create.tsx";
import { useAuth } from "../auth.tsx";
import { ReportEditor } from "../components/report-editor.tsx";
type Row = Record<string, any>;
export function ResearchPage(): React.ReactElement {
  const { t } = useTranslation();
  const { session, openAuth } = useAuth();
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState("researches"), [rows, setRows] = useState<Row[]>([]), [query, setQuery] = useState("");
  const [page, setPage] = useState(1), [size, setSize] = useState(20), [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null), [detail, setDetail] = useState<unknown>(null), [editor, setEditor] = useState(false), [markdown, setMarkdown] = useState("");
  const id = (row: Row): string => row.research_id || row.publication_id || row.report_id;
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void request(tab === "reports" ? "/api/research/reports?scope=all" : "/api/research?scope=all", { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setRows(data.researches || data.reports || data.items || []); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tab, revision]);
  useEffect(() => {
    const controller = new AbortController(); setDetail(null); setMarkdown(""); if (!selected) return;
    if (tab === "reports") {
      void fetch(`/api/research-reports/${encodeURIComponent(id(selected))}/agent.md`, { credentials: "same-origin", signal: controller.signal }).then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text(); }).then((value) => { if (!controller.signal.aborted) setMarkdown(value); }).catch((reason) => { if (!controller.signal.aborted) setDetail({ error: reason.message }); });
    } else void request(`/api/research/${encodeURIComponent(id(selected))}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setDetail(data); }).catch((reason) => { if (!controller.signal.aborted) setDetail({ error: reason.message }); });
    return () => controller.abort();
  }, [selected, tab]);
  const filtered = useMemo(() => rows.filter((row) => !query || `${row.title || ""} ${row.owner || ""}`.toLowerCase().includes(query.toLowerCase())), [rows, query]);
  return <FunctionPage title={t("nav.research")} actions={<>{tab === "researches" ? <Button type="primary" onClick={() => session ? setCreating(true) : openAuth("login")}>{t("research.create")}</Button> : null}<Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision((value) => value + 1)} /></>}>
    <Tabs activeKey={tab} onChange={(value) => { setTab(value); setRows([]); setPage(1); setSelected(null); setEditor(false); }} items={[{ key: "researches", label: t("research.tabResearches") }, { key: "reports", label: t("research.tabReports") }]} />
    <div className="tr-library-filters"><Input.Search allowClear aria-label={t("library.search")} placeholder={t("library.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></div>
    <TRDataTable rows={filtered.slice((page - 1) * size, page * size)} rowKey={id} loading={loading} error={error} pagination={{ page, pageSize: size, total: filtered.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("editor.name"), key: "title", render: (_, row) => <button className="tr-table-link" onClick={() => { setSelected(row); setEditor(false); }}>{row.title || id(row)}</button> },
      { title: t("library.owner"), dataIndex: "owner", responsive: ["md"], render: (value) => value || "—" },
      { title: t("library.visibility"), dataIndex: "visibility", responsive: ["md"], render: (value) => value ? <Tag>{t(`library.scopes.${value}`, { defaultValue: value })}</Tag> : "—" },
      { title: t("jobs.updated"), dataIndex: "updated_at", render: (value) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
    ]} />
    {creating ? <ResearchCreate onClose={() => setCreating(false)} onCreated={(value) => { setCreating(false); setSelected(value); setEditor(false); setRevision(revision => revision + 1); }} /> : null}
    {selected ? <DetailsPanel title={selected.title || id(selected)} onClose={() => { setSelected(null); setEditor(false); }}>
      {tab === "reports" ? <><ReportEditor publicationID={id(selected)} />{markdown ? <details className="tr-report-markdown"><summary>{t("report.markdown")}</summary><pre className="tr-job-detail">{markdown}</pre></details> : null}</>
        : editor ? <iframe className="tr-artifact-frame" title={selected.title || id(selected)} src={`/researches/${encodeURIComponent(id(selected))}?presentation=embedded`} /> : <><ResultView value={detail} /><Button onClick={() => setEditor(true)}>{t("research.openEditor")}</Button></>}
    </DetailsPanel> : null}
  </FunctionPage>;
}
