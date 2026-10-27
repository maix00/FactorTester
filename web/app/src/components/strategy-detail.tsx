import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Collapse, Descriptions, Input, Popconfirm, Select, Spin, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { TRDataTable } from "./data-table.tsx";
import { LibraryCreate } from "./library-create.tsx";
import { ResultView } from "./result-view.tsx";
import { formatDate } from "../format.ts";
type Row = Record<string, any>;
export function StrategyDetail({ detail, onUpdated, onRemoved }: { detail: Row | null; onUpdated: (strategy: Row) => void; onRemoved: () => void }): React.ReactElement {
  const { t } = useTranslation(); const strategy = detail?.strategy || detail;
  const [tab, setTab] = useState("overview"), [selectedRef, setSelectedRef] = useState("");
  const [source, setSource] = useState<Row | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [sourceLoading, setSourceLoading] = useState(false);
  const [expanded, setExpanded] = useState<string[]>([]), [editing, setEditing] = useState<Row | null>(null);
  const [principal, setPrincipal] = useState("");
  const editRequest = useRef<AbortController | null>(null);
  useEffect(() => () => editRequest.current?.abort(), []);
  const [sharePage, setSharePage] = useState(1), [shareSize, setShareSize] = useState(20);
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState(1), [size, setSize] = useState(10);
  const current = strategy?.current_revision || {}, ref = selectedRef || current.revision_ref;
  const revisions: Row[] = strategy?.revisions || [];
  const revision = ref === current.revision_ref ? current : revisions.find((item) => item.revision_ref === ref) || {};
  const needsSource = tab === "source" || expanded.length > 0;
  useEffect(() => {
    if (!strategy?.strategy_ref || !ref || !needsSource || source?.revision_ref === ref) { setSourceLoading(false); return; }
    const controller = new AbortController(); setSourceLoading(true); setError("");
    void request(`/api/strategy-library/strategies/${encodeURIComponent(strategy.strategy_ref)}/revisions/${encodeURIComponent(ref)}?include_source=1`, { signal: controller.signal })
      .then((data) => { if (controller.signal.aborted) return; if (data.revision?.revision_ref !== ref) throw new Error(t("strategyDetail.revisionMismatch")); setSource(data.revision); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setSourceLoading(false); });
    return () => controller.abort();
  }, [strategy?.strategy_ref, ref, needsSource, source?.revision_ref, retry, t]);
  const edit = async (): Promise<void> => {
    setLoading(true); setError("");
    editRequest.current?.abort(); const controller = new AbortController(); editRequest.current = controller;
    try { const data = await request(`/api/strategy-library/strategies/${encodeURIComponent(strategy.strategy_ref)}?include_source=1`, { signal: controller.signal }); if (!controller.signal.aborted) setEditing(data.strategy); }
    catch (reason) { if (!controller.signal.aborted) setError((reason as Error).message); } finally { if (!controller.signal.aborted) setLoading(false); }
  };
  const action = async (suffix: string, method: string, body?: Row): Promise<void> => {
    setLoading(true); setError("");
    try { await request(`/api/strategy-library/strategies/${encodeURIComponent(strategy.strategy_ref)}${suffix}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
      if (method === "DELETE" && !suffix) onRemoved();
      else { const response = await request(`/api/strategy-library/strategies/${encodeURIComponent(strategy.strategy_ref)}?include_source=0`); onUpdated(response.strategy); setPrincipal(""); }
    } catch (reason) { setError((reason as Error).message); } finally { setLoading(false); }
  };
  if (!strategy) return <Spin />;
  if (editing) return <LibraryCreate kind="strategy" strategy={editing} onCancel={() => setEditing(null)} onCreated={(value) => { setEditing(null); setSelectedRef(""); setSource(null); onUpdated(value); }} />;
  const loaded = source?.revision_ref === ref ? source : null;
  const hooks: Row[] = (loaded || revision).hooks || [];
  return <section className="tr-strategy-detail">{error ? <Alert type="error" message={error} action={<Button onClick={() => setRetry((value) => value + 1)}>{t("retry")}</Button>} /> : null}
    <div className="tr-detail-toolbar"><Select aria-label={t("library.version")} value={ref} options={(revisions.length ? revisions : [current]).filter((item) => item.revision_ref).map((item) => ({ value: item.revision_ref, label: `r${item.revision_number || "—"} · ${item.revision_ref}` }))} onChange={(value) => { setSelectedRef(value); setExpanded([]); }} />
      {strategy.access?.can_edit ? <Button disabled={ref !== current.revision_ref} loading={loading} onClick={() => void edit()}>{t("configuration.edit")}</Button> : null}{strategy.access?.can_delete ? <Popconfirm title={t("strategyDetail.archiveConfirm")} onConfirm={() => action("", "DELETE")}><Button danger disabled={loading}>{t("strategyDetail.archive")}</Button></Popconfirm> : null}</div>
    <Tabs activeKey={tab} onChange={setTab} items={[
      { key: "overview", label: t("details"), children: <><Descriptions column={1} items={[
        { key: "strategy", label: t("strategyDetail.reference"), children: strategy.strategy_ref },
        { key: "owner", label: t("library.owner"), children: strategy.owner_ref },
        { key: "description", label: t("library.description"), children: strategy.description || "—" },
        { key: "entry", label: t("editor.entrypoint"), children: revision.entrypoint || "—" },
        { key: "hash", label: t("strategyDetail.sourceHash"), children: revision.source_sha256 || "—" },
      ]} /><Collapse items={hooks.map((hook, index) => ({ key: String(index), label: hook.name || hook.method || `Hook ${index + 1}`, children: sourceLoading ? <Spin /> : <pre className="tr-job-detail">{loaded?.hooks?.[index]?.source || "—"}</pre> }))} activeKey={expanded} onChange={(keys) => setExpanded(Array.isArray(keys) ? keys.map(String) : [String(keys)])} /></> },
      { key: "source", label: t("editor.source"), children: <Spin spinning={sourceLoading}>{loaded ? <pre className="tr-source-view"><code>{loaded.source_code || ""}</code></pre> : null}</Spin> },
      { key: "revisions", label: t("strategyDetail.history"), children: <TRDataTable rows={revisions.slice((page - 1) * size, page * size)} rowKey="revision_ref" pagination={{ page, pageSize: size, total: revisions.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
        { title: t("library.version"), key: "version", render: (_, row) => <button className="tr-table-link" onClick={() => { setSelectedRef(row.revision_ref); setTab("source"); }}>{`r${row.revision_number || "—"}`}</button> },
        { title: t("editor.entrypoint"), dataIndex: "entrypoint" },
        { title: t("strategyDetail.sourceHash"), dataIndex: "source_sha256", ellipsis: true },
        { title: t("strategyDetail.created"), dataIndex: "created_at", render: (value) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
      ]} /> },
      { key: "requirements", label: t("editor.requirements"), children: <ResultView value={revision.requirements} /> },
      ...(strategy.access?.can_share ? [{ key: "shares", label: t("strategyDetail.shares"), children: <><div className="tr-detail-toolbar"><Input aria-label={t("strategyDetail.principal")} value={principal} onChange={(event) => setPrincipal(event.target.value)} /><Button type="primary" loading={loading} disabled={!principal.trim()} onClick={() => void action("/shares", "POST", { principal_ref: principal.trim() })}>{t("strategyDetail.share")}</Button></div>
        <TRDataTable rows={(strategy.shares || []).slice((sharePage - 1) * shareSize, sharePage * shareSize).map((value: string | Row) => typeof value === "string" ? { principal_ref: value } : value)} rowKey="principal_ref" pagination={{ page: sharePage, pageSize: shareSize, total: (strategy.shares || []).length, onChange: (p, s) => { setSharePage(p); setShareSize(s); } }} columns={[
          { title: t("strategyDetail.principal"), key: "principal", render: (_: unknown, row: Row) => row.principal_ref || String(row) },
          { title: t("strategyDetail.revoke"), key: "action", render: (_: unknown, row: Row) => <Popconfirm title={t("strategyDetail.revokeConfirm")} onConfirm={() => action(`/shares/${encodeURIComponent(row.principal_ref || String(row))}`, "DELETE")}><Button danger disabled={loading}>{t("strategyDetail.revoke")}</Button></Popconfirm> },
        ]} /></> }] : []),
    ]} />
  </section>;
}
