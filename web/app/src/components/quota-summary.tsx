import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Collapse, Popconfirm, Progress, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { aggregateQuota, cleanupPlan, type CleanupPlan, type QuotaRecord, type QuotaServer } from "../quota-model.ts";
import { executeCleanup } from "../quota-cleanup.ts";
import { notify } from "../notifications/core.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { TRDataTable } from "./data-table.tsx";
import { ResultView } from "./result-view.tsx";

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / (1024 ** power)).toFixed(2)} ${["KiB", "MiB", "GiB", "TiB"][power - 1]}`;
}

type Inventory = { profile: QuotaRecord; pending: QuotaRecord[]; servers: QuotaServer[]; partial: boolean; ready: boolean };
export function QuotaSummary({ data, onRefresh }: { data: Record<string, any>; onRefresh: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [error, setError] = useState(""), [revision, setRevision] = useState(0), [page, setPage] = useState(1), [size, setSize] = useState(20);
  const [historyOpen, setHistoryOpen] = useState(false), [busy, setBusy] = useState(false);
  const mutation = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    setInventory(null); setError("");
    const load = async (): Promise<void> => {
      // The cached inventory enables an initial display while remote servers are queried.
      const [snapshot, commands] = await Promise.all([
        request("/api/storage/profile-inventory?snapshot=1", { signal: controller.signal }),
        request("/api/storage/deferred-job-cleanup", { signal: controller.signal }),
      ]);
      if (!Array.isArray(commands.requests)) throw new Error(t("quota.invalidCommands"));
      const servers = new Map<string, QuotaServer>();
      for (const row of [...(snapshot.job_snapshots || []), ...(data.servers || [])]) {
        const id = String(row.storage_server_id || "");
        const previous = servers.get(id);
        const observed = (value: unknown): number => typeof value === "number" ? value * 1000 : typeof value === "string" ? Date.parse(value) || 0 : 0;
        if (id && (!previous || observed(row.observed_at) >= observed(previous.observedAt))) servers.set(id, { id, data: row, snapshot: true, observedAt: row.observed_at });
      }
      const id = String(data.storage_server_id || "");
      if (id) servers.set(id, { id, data, snapshot: false });
      const initial: Inventory = { profile: snapshot, pending: commands.requests, servers: [...servers.values()], partial: true, ready: false };
      if (!controller.signal.aborted) setInventory(initial);
      const [liveProfile, ...remote] = await Promise.allSettled([
        request("/api/storage/profile-inventory", { signal: controller.signal }),
        ...initial.servers.filter(server => server.snapshot).map(server => request(`/api/jobs/storage?${new URLSearchParams({ server_id: server.id })}`, { signal: controller.signal })),
      ]);
      if (controller.signal.aborted) return;
      let partial = liveProfile.status === "rejected";
      const remoteServers = initial.servers.filter(server => server.snapshot);
      remote.forEach((result, index) => {
        const server = remoteServers[index];
        if (result.status === "fulfilled" && result.value.storage_server_id === server.id) servers.set(server.id, { id: server.id, data: result.value, snapshot: false });
        else {
          partial = true;
          // Authorization failures and identity mismatches do not prove a server is offline.
          const status = result.status === "rejected" ? result.reason?.status : null;
          if (result.status === "fulfilled" || status === 401 || status === 403) servers.set(server.id, { ...server, queueAllowed: false });
        }
      });
      const profile = liveProfile.status === "fulfilled" ? liveProfile.value : snapshot;
      setInventory({ profile, pending: commands.requests, servers: [...servers.values()], partial: partial || !id || !profile.protected_metadata, ready: true });
    };
    void load().catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => controller.abort();
  }, [data, revision, t]);
  const rows = useMemo(() => inventory ? aggregateQuota(inventory.servers, inventory.profile, inventory.pending) : [], [inventory]);
  const measured = rows.reduce((sum, row) => sum + row.billedBytes, 0);
  const physical = rows.reduce((sum, row) => sum + row.bytes, 0);
  const limit = typeof data.quota_bytes === "number" && data.quota_bytes > 0 ? data.quota_bytes : null;
  const percent = limit === null ? null : measured * 100 / limit;
  const runCleanup = async (plan: CleanupPlan, group = ""): Promise<void> => {
    if (mutation.current || !inventory?.ready) return;
    mutation.current = true; setBusy(true);
    try {
      const result = await executeCleanup(plan, group, request);
      const failures = result.failures.map(item => `${item.server}: ${item.reason.startsWith("failed_files:") ? t("quota.failedFiles", { count: Number(item.reason.slice(13)) }) : item.reason}`);
      notify({ type: failures.length ? "error" : "success", message: t("quota.cleanupResult", { deleted: result.deleted, queued: result.queued }), description: failures.join("；") });
    } finally { mutation.current = false; setBusy(false); onRefresh(); }
  };
  const cancelPending = async (id: string): Promise<void> => {
    if (mutation.current || !id) return;
    mutation.current = true; setBusy(true);
    try {
      await request(`/api/storage/deferred-job-cleanup/${encodeURIComponent(id)}`, { method: "DELETE" });
      notify({ type: "success", message: t("quota.cancelled") });
    } catch (reason) { notify({ type: "error", message: t("quota.cancelFailed"), description: reason instanceof Error ? reason.message : String(reason) }); }
    finally { mutation.current = false; setBusy(false); onRefresh(); }
  };
  const confirmCleanup = (plan: CleanupPlan, group = "", label = "quota.deleteCategory"): React.ReactNode => <Popconfirm title={t("quota.confirmCleanup")} description={t("quota.confirmDetails", { count: plan.count, bytes: bytes(plan.bytes) })} onConfirm={() => runCleanup(plan, group)} okText={t("quota.delete")} cancelText={t("configuration.cancel")}><Button danger disabled={busy || !inventory?.ready || !plan.count}>{t(label)}</Button></Popconfirm>;
  const historyRows: QuotaServer[] = inventory ? [...inventory.servers.filter(server => server.snapshot && Number(server.data.output_bytes) > 0), ...inventory.pending.filter(item => ["pending", "executing"].includes(item.status) && !inventory.servers.some(server => server.id === item.server_id && server.snapshot)).map(item => ({ id: String(item.server_id), data: {}, snapshot: false }))] : [];
  return <section aria-label={t("quota.total")}>
    {error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : null}
    {!inventory && !error ? <Spin tip={t("loading")} /> : null}
    {inventory ? <>
      {inventory.partial ? <Alert type="info" showIcon message={t("quota.partialInventory")} /> : null}
      <h3>{t("quota.total")}: {bytes(measured)} / {limit === null ? "—" : bytes(limit)}</h3>
      {percent !== null ? <Progress percent={Math.min(percent, 100)} status={percent > 100 ? "exception" : "normal"} format={() => `${percent.toFixed(1)}%`} /> : null}
      {physical > measured ? <p>{t("quota.pendingPhysical", { bytes: bytes(physical - measured) })}</p> : null}
      <div className="tr-inline-actions">{confirmCleanup(cleanupPlan(inventory.servers, inventory.pending), "", "quota.autoDelete")}<Button onClick={() => setHistoryOpen(true)} disabled={!historyRows.length}>{t("quota.offlineDetails")}</Button><Button onClick={onRefresh} disabled={busy}>{t("configuration.reload")}</Button></div>
      <TRDataTable rows={rows} rowKey="group" pagination={{ page, pageSize: size, total: rows.length, hideOnSinglePage: true, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
        { key: "category", title: t("quota.category"), render: (_, row) => t(`quota.groups.${row.group}`, { defaultValue: row.group, nsSeparator: false }) },
        { key: "usage", title: t("quota.usage"), render: (_, row) => row.bytes === row.billedBytes ? bytes(row.bytes) : `${bytes(row.billedBytes)} / ${bytes(row.bytes)}` },
        { key: "scope", title: t("quota.scope"), render: (_, row) => t(row.lastObserved.length ? "quota.lastObserved" : "quota.current") },
        { key: "count", title: t("quota.count"), render: (_, row) => row.count || "—" },
        { key: "action", title: t("quota.action"), render: (_, row) => row.group.startsWith("output:") ? confirmCleanup(cleanupPlan(inventory.servers, inventory.pending, row.group), row.group) : t("quota.protected") },
      ]} />
      {historyOpen ? <DetailsPanel title={t("quota.offlineDetails")} onClose={() => setHistoryOpen(false)}><p>{t("quota.offlineExplanation")}</p><TRDataTable rows={historyRows} rowKey="id" pagination={{ page: 1, pageSize: Math.max(20, historyRows.length), total: historyRows.length, hideOnSinglePage: true, onChange: () => undefined }} columns={[
        { key: "server", title: t("quota.server"), render: (_, server) => server.id },
        { key: "usage", title: t("quota.usage"), render: (_, server) => typeof server.data.output_bytes === "number" ? bytes(server.data.output_bytes) : "—" },
        { key: "state", title: t("jobs.status"), render: (_, server) => { const item = inventory.pending.find(value => value.server_id === server.id && ["pending", "executing"].includes(value.status)); return item ? t(item.status === "pending" ? "quota.pending" : "quota.executing") : t("quota.current"); } },
        { key: "action", title: t("quota.action"), render: (_, server) => { const item = inventory.pending.find(value => value.server_id === server.id && ["pending", "executing"].includes(value.status)); return item ? item.status === "pending" ? <Popconfirm title={t("quota.confirmCancel")} onConfirm={() => cancelPending(String(item.request_id || ""))} okText={t("quota.cancelPending")} cancelText={t("configuration.cancel")}><Button disabled={busy || !item.request_id}>{t("quota.cancelPending")}</Button></Popconfirm> : t("quota.executing") : confirmCleanup(cleanupPlan([server], inventory.pending, "output:historical"), "output:historical", "quota.schedule"); } },
      ]} /></DetailsPanel> : null}
    </> : null}
    <Collapse ghost items={[{ key: "raw", label: t("quota.details"), children: <ResultView value={data} /> }]} />
  </section>;
}
