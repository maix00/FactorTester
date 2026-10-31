import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Form, Input, Modal, Popconfirm, Select, Spin, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { formatDate } from "../format.ts";
import { notify } from "../notifications/core.ts";
import { downloadBlob } from "../download.ts";
import { evidenceFile } from "../research-evidence-download.ts";
import { reportRowID, researchRelationCandidates } from "../research-model.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { ObjectReference } from "./object-reference.tsx";
import { ResearchEvidenceEditor } from "./research-evidence-editor.tsx";
import { ResearchSharing } from "./research-sharing.tsx";
import { ResultView } from "./result-view.tsx";
import { TRDataTable } from "./data-table.tsx";

type Row = Record<string, any>;
type CreateKind = "profile" | "workspace" | "report";

/** Research relations use the same authorized catalog endpoints as the legacy view. */
export function ResearchRelations({ research, overview, onReport, onResearch, onSectionChange, showLegacyVisibility = false }: { research: Row; overview: React.ReactNode; onReport: (value: Row) => void; onResearch: (value: Row) => void; onSectionChange?: (section:string) => void; showLegacyVisibility?:boolean }): React.ReactElement {
  const { t } = useTranslation();
  const id = String(research.research_id || "");
  const base = `/api/research/${encodeURIComponent(id)}`;
  const [tab, setTab] = useState("details"), [rows, setRows] = useState<Row[]>([]), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [page, setPage] = useState(1), [size, setSize] = useState(20), [total, setTotal] = useState(0), [revision, setRevision] = useState(0);
  const [create, setCreate] = useState<CreateKind | null>(null), [choices, setChoices] = useState<Row[]>([]), [choice, setChoice] = useState(""), [title, setTitle] = useState("");
  const [choiceLoading, setChoiceLoading] = useState(false), [choiceError, setChoiceError] = useState(""), [busy, setBusy] = useState(false);
  const [evidence, setEvidence] = useState<Row | null>(null);
  const mutation = useRef(false);
  const canManage = research.access?.can_manage === true;
  useEffect(() => {
    if (tab === "details" || tab === "sharing") return;
    const controller = new AbortController(); setLoading(true); setError(""); setRows([]);
    const endpoint = tab === "evidence" ? `/api/research-evidence/catalog/research/${encodeURIComponent(id)}?page=${page}&page_size=${size}` : `${base}/${tab}`;
    void request(endpoint, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      const data = tab === "evidence" ? value.catalog : value;
      const list = tab === "evidence" ? data?.items : data?.[tab];
      if (!Array.isArray(list)) throw new Error(t("researchDetail.invalidResponse"));
      setRows(list); setTotal(tab === "evidence" ? Number(data.total || 0) : list.length);
    }).catch(reason => { if (!controller.signal.aborted) setError(String(reason.message || reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, id, tab, tab === "evidence" ? page : 0, tab === "evidence" ? size : 0, revision, t]);
  useEffect(() => {
    if (!create) return;
    const controller = new AbortController(); setChoices([]); setChoice(""); setTitle(""); setChoiceError(""); setChoiceLoading(true);
    const url = create === "profile" ? "/api/client/profiles" : `${base}/members`;
    const existingURL = create === "profile" ? `${base}/members` : create === "workspace" ? `${base}/workspaces` : "";
    void Promise.all([request(url, { signal: controller.signal }), existingURL ? request(existingURL, { signal: controller.signal }) : Promise.resolve(null)]).then(([value, existing]) => {
      if (controller.signal.aborted) return;
      const list = create === "profile" ? value.profiles : value.members;
      if (!Array.isArray(list)) throw new Error(t("researchDetail.invalidResponse"));
      if (create === "profile" && !Array.isArray(existing?.members) || create === "workspace" && !Array.isArray(existing?.workspaces)) throw new Error(t("researchDetail.invalidResponse"));
      setChoices(researchRelationCandidates(create, list, existing || {}, String(research.owner_ref || "")));
    }).catch(reason => { if (!controller.signal.aborted) setChoiceError(String(reason.message || reason)); })
      .finally(() => { if (!controller.signal.aborted) setChoiceLoading(false); });
    return () => controller.abort();
  }, [base, create, t]);
  const refresh = (): void => setRevision(value => value + 1);
  const perform = async (code: string, action: () => Promise<void | boolean>): Promise<void> => {
    if (mutation.current) return;
    mutation.current = true; setBusy(true);
    try { const complete = await action(); if (complete !== false) notify({ code: `research.${code}.success`, type: "success", message: t(`researchDetail.notices.${code}`) }); refresh(); }
    catch (reason) { notify({ code: `research.${code}.failed`, type: "error", message: t("researchDetail.operationFailed"), description: reason instanceof Error ? reason.message : String(reason) }); }
    finally { mutation.current = false; setBusy(false); }
  };
  const createRelation = (): void => {
    const selected = choices.find(row => JSON.stringify([row.principal_ref || row.owner_ref || research.owner_ref || "", row.profile_ref || row.profile_id || ""]) === choice);
    if (!create || !selected) return;
    const principal = String(selected.principal_ref || selected.owner_ref || research.owner_ref || "");
    const profile = String(selected.profile_ref || selected.profile_id || "");
    void perform(create, async () => {
      if (create === "profile") {
        await request(`${base}/members`, { method: "POST", body: JSON.stringify({ principal_ref: principal, profile_ref: profile, role: "contributor", status: "active" }) });
        // Membership is already durable if the independent workspace request fails.
        try { await request(`${base}/workspaces`, { method: "POST", body: JSON.stringify({ principal_ref: principal, profile_ref: profile, title: `${research.title} / ${profile}` }) }); }
        catch (reason) { setCreate(null); notify({ code: "research.profile.workspace-failed", type: "warning", message: t("researchDetail.workspacePartial"), description: reason instanceof Error ? reason.message : String(reason) }); return false; }
      } else if (create === "workspace") {
        await request(`${base}/workspaces`, { method: "POST", body: JSON.stringify({ principal_ref: principal, profile_ref: profile, title: title.trim() || `${research.title} / ${profile}` }) });
      } else {
        await request(`${base}/reports`, { method: "POST", body: JSON.stringify({ title: title.trim(), profile_ref: profile, visibility: "private" }) });
      }
      setCreate(null);
    });
  };
  const selectTab = (value: string): void => { setTab(value); setRows([]); setPage(1); setSize(20); setError(""); onSectionChange?.(value); };
  const visible = tab === "evidence" ? rows : rows.slice((page - 1) * size, page * size);
  const table = (columns: any[], rowKey: (row: Row) => string): React.ReactElement => <TRDataTable rows={visible} columns={columns} rowKey={rowKey} loading={loading} error={error} pagination={{ page, pageSize: size, total, onChange: (next, nextSize) => { setPage(next); setSize(nextSize); } }} />;
  return <section className="tr-research-relations">
    <Tabs activeKey={tab} onChange={selectTab} items={[
      { key: "details", label: t("details") }, { key: "reports", label: t("researchDetail.reports") },
      { key: "evidence", label: t("researchDetail.evidence") }, { key: "members", label: t("research.profile") }, { key: "workspaces", label: t("researchDetail.workspaces") }, {key:"sharing",label:t("researchSharing.title")},
    ]} />
    {tab === "details" ? overview : <>
      {tab === "sharing" ? <ResearchSharing target={{researchId:id}} /> : null}
      {canManage && ["reports", "members", "workspaces"].includes(tab) ? <div className="tr-research-relations-actions"><Button type="primary" onClick={() => setCreate(tab === "members" ? "profile" : tab === "reports" ? "report" : "workspace")}>{t(`researchDetail.create.${tab}`)}</Button></div> : null}
      {tab === "reports" ? table([
        { title: t("editor.name"), key: "title", render: (_: unknown, row: Row) => <button type="button" className="tr-table-link" onClick={() => onReport({ ...row, research_id: row.research_id || id })}>{row.title || reportRowID(row)}</button> },
        { title: t("research.profile"), key: "profile", render: (_: unknown, row: Row) => row.profile_ref ? <ObjectReference value={{kind:"profile",ref:String(row.profile_ref),profileKey:row.profile_key,owner:row.owner_ref}} /> : "—" },
        ...(showLegacyVisibility ? [{ title: t("library.visibility"), key: "visibility", render: (_: unknown, row: Row) => row.visibility ? t(`research.visibility.${row.visibility}`, {defaultValue:row.visibility}) : "—" }] : []),
        { title: t("jobs.updated"), key: "updated", render: (_: unknown, row: Row) => row.updated_at ? formatDate(row.updated_at, {dateStyle:"medium",timeStyle:"short"}) : "—" },
        { title: t("jobs.action"), key: "action", render: (_: unknown, row: Row) => row.report_id && row.access?.can_manage === true && row.can_delete === true ? <Popconfirm title={t("researchDetail.deleteReportConfirm")} onConfirm={() => void perform("deleteReport", async () => { await request(`${base}/reports/${encodeURIComponent(String(row.report_id))}`, {method:"DELETE"}); })}><Button danger disabled={busy}>{t("configuration.remove")}</Button></Popconfirm> : "—" },
      ], row => reportRowID(row)) : null}
      {tab === "evidence" ? table([
        { title: t("researchDetail.evidence"), key: "name", render: (_: unknown, row: Row) => <button type="button" className="tr-table-link" onClick={() => setEvidence(row)}>{row.title_zh || row.evidence_ref}</button> },
        { title: t("researchDetail.kind"), dataIndex:"evidence_kind" }, { title: t("researchDetail.summary"), dataIndex:"claim_summary" }, { title: t("researchDetail.reportCount"), dataIndex:"report_count" },
      ], row => String(row.evidence_ref)) : null}
      {tab === "members" ? table([
        { title: t("adminFunctions.user"), key:"principal", render: (_: unknown, row: Row) => <ObjectReference value={{kind:"user",ref:String(row.principal_ref || "")}} /> },
        { title: t("research.profile"), key:"profile", render: (_: unknown, row: Row) => <ObjectReference value={{kind:"profile",ref:String(row.profile_ref || ""),profileKey:row.profile_key,owner:row.principal_ref}} /> },
        { title: t("settingsPanel.role"), dataIndex:"role", render: (role: string) => role ? t(`researchDetail.roles.${role}`, {defaultValue:role}) : "—" },
        { title: t("jobs.action"), key:"action", render: (_: unknown, row: Row) => canManage && !(String(row.profile_ref) === "self" && row.principal_ref === research.owner_ref) ? <Popconfirm title={t("researchDetail.removeProfileConfirm")} onConfirm={() => void perform("removeProfile", async () => { await request(`${base}/members/${encodeURIComponent(String(row.profile_ref))}?${new URLSearchParams({principal_ref:String(row.principal_ref)})}`, {method:"DELETE"}); })}><Button danger disabled={busy}>{t("configuration.remove")}</Button></Popconfirm> : "—" },
      ], row => JSON.stringify([row.principal_ref,row.profile_ref])) : null}
      {tab === "workspaces" ? table([
        { title: t("research.profile"), key:"profile", render: (_: unknown, row: Row) => <ObjectReference value={{kind:"profile",ref:String(row.profile_ref || ""),profileKey:row.profile_key,owner:row.principal_ref}} /> },
        { title: t("researchDetail.workspace"), key:"workspace", render: (_: unknown, row: Row) => row.title || row.workspace_id || "—" },
        { title: t("jobs.status"), dataIndex:"status", render: (status: string) => status ? t(`researchDetail.status.${status}`, {defaultValue:status}) : "—" }, { title: t("jobs.updated"), key:"updated", render: (_: unknown, row: Row) => row.updated_at ? formatDate(row.updated_at, {dateStyle:"medium",timeStyle:"short"}) : "—" },
      ], row => String(row.workspace_id)) : null}
    </>}
    <Modal open={!!create} title={create ? t(`researchDetail.create.${create === "profile" ? "members" : `${create}s`}`) : ""} onCancel={() => setCreate(null)} footer={null} destroyOnHidden>
      {choiceError ? <Alert type="error" showIcon message={t("loadFailed")} description={choiceError} /> : null}
      <Form layout="vertical" onFinish={createRelation}>
        {(create === "report" || create === "workspace") ? <Form.Item label={t("editor.name")} required={create === "report"}><Input aria-label={t("editor.name")} value={title} onChange={event => setTitle(event.target.value)} /></Form.Item> : null}
        <Form.Item label={t("research.profile")} required><Select aria-label={t("research.profile")} loading={choiceLoading} value={choice || undefined} options={choices.map(row => ({ value:JSON.stringify([row.principal_ref || row.owner_ref || research.owner_ref || "",row.profile_ref || row.profile_id || ""]),label:String(row.display_name || row.profile_ref || row.profile_id || "") }))} onChange={setChoice} /></Form.Item>
        <Button type="primary" htmlType="submit" aria-label={t("configuration.add")} loading={busy} disabled={choiceLoading || !!choiceError || !choice || create === "report" && !title.trim()}>{t("configuration.add")}</Button>
      </Form>
    </Modal>
    {evidence ? <ResearchEvidence evidence={evidence} onClose={() => setEvidence(null)} onReport={onReport} onResearch={onResearch} /> : null}
  </section>;
}

function ResearchEvidence({ evidence, onClose, onReport, onResearch }: { evidence: Row; onClose: () => void; onReport: (value: Row) => void; onResearch: (value: Row) => void }): React.ReactElement {
  const { t } = useTranslation(); const ref = String(evidence.evidence_ref || "");
  const [tab, setTab] = useState("overview"), [value, setValue] = useState<unknown>(null), [error, setError] = useState("");
  const [canManage, setCanManage] = useState(false), [editing, setEditing] = useState(false), [revision, setRevision] = useState(0);
  const [canDownload, setCanDownload] = useState(false), [page, setPage] = useState(1), [size, setSize] = useState(20), [busy, setBusy] = useState(false);
  const pending = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setValue(null); setError(""); setCanManage(false); setCanDownload(false);
    const endpoint = tab === "overview" ? `/api/research-evidence/catalog/${encodeURIComponent(ref)}/summary` : tab === "relationships" ? `/api/research-evidence/catalog/${encodeURIComponent(ref)}/relationships?page=${page}&page_size=${size}` : `/api/research-evidence/${encodeURIComponent(ref)}`;
    void request(endpoint, {signal:controller.signal}).then(result => {if (!controller.signal.aborted) { setValue(tab === "relationships" ? result.relationships : result.evidence); setCanManage(result.access?.can_manage === true); setCanDownload(result.access?.can_download === true); }}).catch(reason => {if (!controller.signal.aborted) setError(String(reason.message || reason));});
    return () => controller.abort();
  }, [ref,tab,revision,tab === "relationships" ? page : 0,tab === "relationships" ? size : 0]);
  const run = async (action: () => Promise<void>): Promise<void> => {
    if (pending.current) return;
    pending.current = true; setBusy(true);
    try { await action(); } catch (reason) {
      const text = reason instanceof Error ? reason.message : String(reason);
      const description = text === "invalid_transfer_access" ? t("researchEvidence.invalidTransfer") : text === "evidence_size_mismatch" ? t("researchEvidence.sizeMismatch") : text;
      notify({code:"research.evidence.action.failed",type:"error",message:t("researchDetail.operationFailed"),description});
    }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  const openReport = (row: Row): void => { void run(async () => {
    if (!row.research_id || !row.report_id) throw new Error(t("researchEvidence.reportUnavailable"));
    const result = await request(`/api/research/${encodeURIComponent(String(row.research_id))}/reports`);
    const report = Array.isArray(result.reports) ? result.reports.find((item: Row) => item.report_id === row.report_id) : null;
    if (!report) throw new Error(t("researchEvidence.reportUnavailable"));
    onReport({...report,research_id:row.research_id});
  }); };
  const download = (row: Row): void => { void run(async () => {
    const result = await evidenceFile(ref, String(row.source_ref || ""));
    downloadBlob(result.blob, result.filename || String(row.source?.identity?.filename || "evidence-file"));
  }); };
  const fragments = tab === "fragments" && Array.isArray((value as Row | null)?.fragments) ? (value as Row).fragments as Row[] : [];
  const relationships = tab === "relationships" && value && Array.isArray((value as Row).items) ? value as Row : null;
  return <DetailsPanel title={evidence.title_zh || ref} onClose={onClose}>{editing
    ? <ResearchEvidenceEditor evidenceRef={ref} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); setRevision(current => current + 1); }} />
    : <><Tabs activeKey={tab} onChange={next => {setTab(next);setPage(1);setSize(20);}} items={[{key:"overview",label:t("jobs.overview")},{key:"fragments",label:t("researchDetail.fragments")},{key:"relationships",label:t("researchDetail.relationships") }]} />
      {error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} /> : value ? <>
        {tab === "overview" ? <>{canManage ? <Button onClick={() => setEditing(true)}>{t("researchEvidence.edit")}</Button> : null}<ResultView value={value} /></> : null}
        {tab === "fragments" ? <TRDataTable<Row> rows={fragments.slice((page-1)*size,page*size)} rowKey={row => String(row.fragment_ref || row.source_ref)} pagination={{page,pageSize:size,total:fragments.length,onChange:(next,nextSize) => {setPage(next);setSize(nextSize);}}} columns={[
          {title:t("researchEvidence.fragment"),key:"title",render:(_:unknown,row:Row) => row.title_zh || row.fragment_ref || "—"},
          {title:t("researchEvidence.sourceType"),key:"kind",render:(_:unknown,row:Row) => row.source?.source_kind || "—"},
          {title:t("researchDetail.summary"),dataIndex:"summary_zh"},
          {title:t("researchEvidence.selector"),key:"selector",render:(_:unknown,row:Row) => row.selector ? <details><summary>{t("details")}</summary><ResultView value={row.selector} /></details> : "—"},
          {title:t("jobs.action"),key:"action",render:(_:unknown,row:Row) => row.source?.source_kind !== "file" ? "—" : !canDownload ? t("researchEvidence.previewOnly") : !row.source_ref || !row.source?.identity?.object_id || !row.source?.identity?.storage_server_id ? t("researchEvidence.fileUnavailable") : <Button disabled={busy} onClick={() => download(row)}>{t("jobs.download")}</Button>},
        ]} /> : null}
        {tab === "relationships" ? relationships ? <TRDataTable<Row> rows={relationships.items} rowKey={row => String(row.link_ref)} pagination={{page,pageSize:size,total:Number(relationships.total || 0),onChange:(next,nextSize) => {setPage(next);setSize(nextSize);}}} columns={[
          {title:t("researchDetail.reports"),key:"report",render:(_:unknown,row:Row) => row.report_id && row.research_id ? <button type="button" className="tr-table-link" disabled={busy} onClick={() => openReport(row)}>{row.report_title || row.report_id}</button> : row.report_title || row.report_id || "—"},
          {title:t("research.tabResearches"),key:"research",render:(_:unknown,row:Row) => row.research_id ? <button type="button" className="tr-table-link" onClick={() => onResearch({research_id:row.research_id,title:row.research_title || row.research_id})}>{row.research_title || row.research_id}</button> : "—"},
          {title:t("researchEvidence.purpose"),dataIndex:"purpose"},
          {title:t("research.profile"),key:"profile",render:(_:unknown,row:Row) => row.profile_ref ? <ObjectReference value={{kind:"profile",ref:String(row.profile_ref)}} /> : "—"},
          {title:t("jobs.updated"),key:"time",render:(_:unknown,row:Row) => row.created_at ? formatDate(row.created_at, {dateStyle:"medium",timeStyle:"short"}) : "—"},
        ]} /> : <Alert type="error" showIcon message={t("researchDetail.invalidResponse")} /> : null}
      </> : <Spin />}</>}
  </DetailsPanel>;
}
