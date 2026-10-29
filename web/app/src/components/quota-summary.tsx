import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Collapse, Progress, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { aggregateQuota, type QuotaRecord, type QuotaServer } from "../quota-model.ts";
import { TRDataTable } from "./data-table.tsx";
import { ResultView } from "./result-view.tsx";

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / (1024 ** power)).toFixed(2)} ${["KiB", "MiB", "GiB", "TiB"][power - 1]}`;
}

type Inventory = { profile: QuotaRecord; pending: QuotaRecord[]; servers: QuotaServer[]; partial: boolean };
export function QuotaSummary({ data }: { data: Record<string, any> }): React.ReactElement {
  const { t } = useTranslation();
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [error, setError] = useState(""), [revision, setRevision] = useState(0), [page, setPage] = useState(1), [size, setSize] = useState(20);
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
      const initial: Inventory = { profile: snapshot, pending: commands.requests, servers: [...servers.values()], partial: true };
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
        else partial = true;
      });
      const profile = liveProfile.status === "fulfilled" ? liveProfile.value : snapshot;
      setInventory({ profile, pending: commands.requests, servers: [...servers.values()], partial: partial || !id || !profile.protected_metadata });
    };
    void load().catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => controller.abort();
  }, [data, revision, t]);
  const rows = useMemo(() => inventory ? aggregateQuota(inventory.servers, inventory.profile, inventory.pending) : [], [inventory]);
  const measured = rows.reduce((sum, row) => sum + row.billedBytes, 0);
  const physical = rows.reduce((sum, row) => sum + row.bytes, 0);
  const limit = typeof data.quota_bytes === "number" && data.quota_bytes > 0 ? data.quota_bytes : null;
  const percent = limit === null ? null : measured * 100 / limit;
  return <section aria-label={t("quota.total")}>
    {error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : null}
    {!inventory && !error ? <Spin tip={t("loading")} /> : null}
    {inventory ? <>
      <Alert type="info" showIcon message={t(inventory.partial ? "quota.partialInventory" : "quota.cleanupPending")} />
      <h3>{t("quota.total")}: {bytes(measured)} / {limit === null ? "—" : bytes(limit)}</h3>
      {percent !== null ? <Progress percent={Math.min(percent, 100)} status={percent > 100 ? "exception" : "normal"} format={() => `${percent.toFixed(1)}%`} /> : null}
      {physical > measured ? <p>{t("quota.pendingPhysical", { bytes: bytes(physical - measured) })}</p> : null}
      <TRDataTable rows={rows} rowKey="group" pagination={{ page, pageSize: size, total: rows.length, hideOnSinglePage: true, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
        { key: "category", title: t("quota.category"), render: (_, row) => t(`quota.groups.${row.group}`, { defaultValue: row.group, nsSeparator: false }) },
        { key: "usage", title: t("quota.usage"), render: (_, row) => row.bytes === row.billedBytes ? bytes(row.bytes) : `${bytes(row.billedBytes)} / ${bytes(row.bytes)}` },
        { key: "scope", title: t("quota.scope"), render: (_, row) => t(row.lastObserved.length ? "quota.lastObserved" : "quota.current") },
        { key: "count", title: t("quota.count"), render: (_, row) => row.count || "—" },
      ]} />
    </> : null}
    <Collapse ghost items={[{ key: "raw", label: t("quota.details"), children: <ResultView value={data} /> }]} />
  </section>;
}
