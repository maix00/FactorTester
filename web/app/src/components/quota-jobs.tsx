import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { deleteJobOutputs, jobCleanupPreview } from "../quota-cleanup.ts";
import { notify } from "../notifications/core.ts";
import { formatQuotaBytes, type QuotaServer } from "../quota-model.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { TRDataTable } from "./data-table.tsx";

type Job = { server: string; job_id: string; job_kind?: string; job_status?: string; bytes?: number };
export function QuotaJobs({ group, servers, onClose, onRefresh }: { group: string; servers: QuotaServer[]; onClose: () => void; onRefresh: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const [rows, setRows] = useState<Job[]>([]), [error, setError] = useState(""), [loading, setLoading] = useState(false), [preview, setPreview] = useState<{ job: Job; value: any } | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const offsets = useRef(new Map<string, number>()), finished = useRef(new Set<string>()), inFlight = useRef(false), mounted = useRef(true);
  const load = async (): Promise<void> => {
    if (inFlight.current) return;
    inFlight.current = true; setLoading(true); setError("");
    const targets = servers.filter(server => !server.snapshot && !finished.current.has(server.id));
    const results = await Promise.allSettled(targets.map(server => request(`/api/jobs/storage?${new URLSearchParams({ server_id: server.id, group, limit: "100", offset: String(offsets.current.get(server.id) || 0) })}`)));
    if (!mounted.current) return;
    const next: Job[] = [], errors: string[] = [];
    results.forEach((result, index) => {
      const server = targets[index];
      if (result.status === "rejected") { errors.push(`${server.id}: ${result.reason?.message || result.reason}`); return; }
      const value = result.value;
      if (value.storage_server_id !== server.id || !Array.isArray(value.jobs)) { errors.push(`${server.id}: ${t("quota.invalidJobs")}`); return; }
      const batch = value.jobs as Job[], offset = (offsets.current.get(server.id) || 0) + batch.length;
      if (!batch.length && offset < Number(value.job_count || 0)) { errors.push(`${server.id}: ${t("quota.invalidJobs")}`); return; }
      next.push(...batch.map(job => ({ ...job, server: server.id })));
      offsets.current.set(server.id, offset);
      if (offset >= Number(value.job_count || 0)) finished.current.add(server.id);
    });
    setRows(current => [...current, ...next]); setError(errors.join("；"));
    setHasMore(servers.some(server => !server.snapshot && !finished.current.has(server.id)));
    setLoading(false); inFlight.current = false;
  };
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false; }; }, []);
  const prepare = async (job: Job): Promise<void> => {
    if (inFlight.current) return;
    inFlight.current = true; setLoading(true); setError("");
    try { const value = await jobCleanupPreview(job.server, job.job_id, request); if (mounted.current) setPreview({ job, value }); }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { inFlight.current = false; if (mounted.current) setLoading(false); }
  };
  const remove = async (): Promise<void> => {
    if (!preview || inFlight.current) return;
    inFlight.current = true; setLoading(true);
    try {
      const result = await deleteJobOutputs(preview.job.server, preview.job.job_id, preview.value, request);
      notify({ type: result.failed_files ? "error" : "success", message: t("quota.cleanupResult", { deleted: result.deleted_artifacts || 0, queued: 0 }), description: result.failed_files ? t("quota.failedFiles", { count: result.failed_files }) : undefined });
      onRefresh(); onClose();
    } catch (reason) { if (mounted.current) { setPreview(null); setError(reason instanceof Error ? reason.message : String(reason)); } }
    finally { inFlight.current = false; if (mounted.current) setLoading(false); }
  };
  return <DetailsPanel title={t("quota.jobDetails")} onClose={onClose}>
    {error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} /> : null}
    <TRDataTable rows={rows} rowKey={row => JSON.stringify([row.server, row.job_id])} loading={loading} pagination={{ page: 1, pageSize: Math.max(20, rows.length), total: rows.length, hideOnSinglePage: true, onChange: () => undefined }} columns={[
      { title: t("quota.job"), dataIndex: "job_id" }, { title: t("quota.server"), dataIndex: "server" }, { title: t("quota.usage"), render: (_, row) => typeof row.bytes === "number" ? formatQuotaBytes(row.bytes) : "—" }, { title: t("jobs.status"), dataIndex: "job_status" },
      { title: t("quota.action"), render: (_, row) => preview?.job.server === row.server && preview.job.job_id === row.job_id ? <Popconfirm open title={t("quota.confirmJob")} description={t("quota.confirmJobDetails", { count: preview.value.artifact_count, bytes: formatQuotaBytes(preview.value.bytes) })} onConfirm={() => void remove()} onCancel={() => setPreview(null)} okText={t("quota.delete")} cancelText={t("configuration.cancel")}><Button danger disabled={loading}>{t("quota.deleteJob")}</Button></Popconfirm> : <Button danger disabled={loading || !["succeeded", "failed", "cancelled"].includes(String(row.job_status))} onClick={() => void prepare(row)}>{t("quota.deleteJob")}</Button> },
    ]} />
    {hasMore ? <Button disabled={loading} onClick={() => void load()}>{t("quota.loadMore")}</Button> : null}
  </DetailsPanel>;
}
