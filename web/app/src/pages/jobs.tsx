import React, { useEffect, useState } from "react";
import { Button, Input, Select, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { FunctionPage } from "../components/function-page.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { JobDetail } from "../components/job-detail.tsx";
import { request } from "../configuration/api.ts";
import { usePageInstance } from "../page-instance.ts";
import type { JobReference } from "../job-model.ts";
import { formatDate } from "../format.ts";
export function JobsPage(): React.ReactElement {
  const { t } = useTranslation(); const instance = usePageInstance();
  const [rows, setRows] = useState<any[]>([]), [status, setStatus] = useState<string[]>([]), [page, setPage] = useState(1), [size, setSize] = useState(20), [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false), [error, setError] = useState(""), [revision, setRevision] = useState(0);
  useEffect(() => {
    if (instance.active === false) return;
    const controller = new AbortController(); setLoading(true); setError("");
    const params = new URLSearchParams({ page: String(page), limit: String(size) }); if (status.length) params.set("status", status.join(","));
    request(`/api/jobs?${params}`, { signal: controller.signal }).then((data) => { setRows(data.jobs ?? data.items ?? []); setTotal(data.total || 0); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, size, status, revision, instance.active]);
  return <FunctionPage title={t("nav.jobs")} actions={<Button onClick={() => setRevision((value) => value + 1)}>{t("configuration.reload")}</Button>}>
    <div className="tr-page-filters"><Select mode="multiple" aria-label={t("jobs.statusFilter")} placeholder={t("jobs.statusFilter")} style={{ minWidth: 240 }} value={status} options={["queued", "running", "paused", "succeeded", "failed", "cancelled"].map((value) => ({ value, label: t(`jobs.states.${value}`) }))} onChange={(value) => { setStatus(value); setPage(1); }} /></div>
    <TRDataTable rows={rows} rowKey={(row) => `${row.server_id || ""}:${row.job_id}`} loading={loading} error={error} pagination={{ page, pageSize: size, total, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("jobs.task"), key: "task", render: (_, row) => <button className="tr-table-link" onClick={() => instance.open("job-detail", { jobId: row.job_id, serverId: row.server_id, servicePort: row.service_port })}>{row.task_name || row.kind || row.job_id}</button> },
      { title: t("jobs.status"), dataIndex: "status", render: (value) => <Tag>{t(`jobs.states.${value}`, { defaultValue: value })}</Tag> },
      { title: t("jobs.updated"), dataIndex: "updated_at", render: (value) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
      { title: t("jobs.jobId"), dataIndex: "job_id", ellipsis: true },
    ]} />
  </FunctionPage>;
}
export function JobDetailPage(): React.ReactElement {
  const { t } = useTranslation(); const instance = usePageInstance();
  return <FunctionPage title={t("jobs.detail")}><JobDetail job={{ job_id: instance.args.jobId || "", server_id: instance.args.serverId, service_port: instance.args.servicePort } as JobReference} /></FunctionPage>;
}
