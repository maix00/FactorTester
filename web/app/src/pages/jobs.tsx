import React, { useEffect, useState } from "react";
import { Drawer, Tabs, Tag, Typography } from "antd";
import type { TableProps } from "antd";
import { useTranslation } from "react-i18next";
import { TRDataTable } from "../components/data-table.tsx";
import { TRMultiSelectFilter } from "../components/multi-select.tsx";
import { notify } from "../notifications/core.ts";
import { formatDate } from "../format.ts";

type JobRow = {
  job_id?: string;
  status?: string;
  task_name?: string;
  updated_at?: string;
  kind?: string;
};

const STATUS_OPTIONS = ["succeeded", "running", "failed", "cancelled"].map((value) => ({ value, label: value }));

function statusColor(status = ""): string {
  if (status === "succeeded") return "green";
  if (status === "running") return "blue";
  if (status === "failed") return "red";
  if (status === "cancelled") return "default";
  return "default";
}

export function JobsPage(): React.ReactElement {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<JobRow | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), limit: String(pageSize) });
    if (statuses.length) params.set("status", statuses.join(","));
    setLoading(true);
    setError("");
    fetch(`/api/jobs?${params}`, { credentials: "same-origin", signal: controller.signal })
      .then(async (response) => {
        const value = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
        return value;
      })
      .then((value) => {
        setJobs(Array.isArray(value.jobs) ? value.jobs : []);
        setTotal(Number(value.total || 0));
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, pageSize, statuses]);

  useEffect(() => {
    if (error) notify({
      code: "jobs.load_failed", type: "error",
      message: t("loadFailed"), description: error, duration: 8,
    });
  }, [error, t]);

  useEffect(() => {
    if (!selected?.job_id) return;
    setDetail(null);
    fetch(`/api/jobs/${encodeURIComponent(selected.job_id)}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setDetail(value))
      .catch((reason: Error) => notify({ code: "jobs.detail", type: "error", message: t("loadFailed"), description: reason.message }));
  }, [selected, t]);

  const columns: TableProps<JobRow>["columns"] = [
    {
      title: t("jobs.task"),
      dataIndex: "task_name",
      key: "task",
      ellipsis: true,
      render: (value: string, row) => (
        <button type="button" className="tr-table-link" onClick={() => setSelected(row)}>
          {value || row.kind || row.job_id || "运行"}
        </button>
      ),
    },
    {
      title: t("jobs.status"),
      dataIndex: "status",
      key: "status",
      width: 120,
      render: (value: string) => <Tag color={statusColor(value)}>{value || "unknown"}</Tag>,
    },
    {
      title: t("jobs.updated"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (value: string) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—",
    },
    {
      title: t("jobs.jobId"),
      dataIndex: "job_id",
      key: "job_id",
      width: 220,
      ellipsis: true,
      render: (value: string) => <Typography.Text type="secondary">{value}</Typography.Text>,
    },
  ];

  return (
    <section className="tr-antd-panel">
      <div className="tr-antd-toolbar">
        <TRMultiSelectFilter
          label={t("jobs.statusFilter")}
          placeholder={t("jobs.statusFilter")}
          options={STATUS_OPTIONS}
          value={statuses}
          onChange={(values) => { setStatuses(values); setPage(1); }}
        />
        <span className="tr-antd-total">{t("total", { count: total })}</span>
      </div>
      <Drawer title={selected?.task_name || selected?.job_id || t("jobs.detail")} placement="right" width={620} open={Boolean(selected)} onClose={() => setSelected(null)}>
        {detail ? (<>
          <div className="tr-job-actions">
            {selected?.status === "running" || selected?.status === "queued" ? (
              <button type="button" className="tr-toolbar-button" disabled={loading} onClick={() => {
                if (!selected?.job_id) return;
                fetch(`/api/jobs/${encodeURIComponent(selected.job_id)}/cancel`, { method: "POST", credentials: "same-origin" })
                  .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
                  .then(() => notify({ code: "jobs.cancelled", type: "success", message: t("jobs.cancelled"), duration: 4 }))
                  .catch((reason: Error) => notify({ code: "jobs.cancel_failed", type: "error", message: t("loadFailed"), description: reason.message }));
              }}>{t("jobs.cancel")}</button>
            ) : null}
          </div>
          <Tabs
            items={[
              { key: "summary", label: t("jobs.detail"), children: <pre className="tr-job-detail">{JSON.stringify(detail, null, 2)}</pre> },
              { key: "configuration", label: t("jobs.configuration"), children: <pre className="tr-job-detail">{JSON.stringify(detail.execution_plan ?? detail.job_spec ?? detail.run_spec ?? null, null, 2)}</pre> },
              { key: "inputs", label: t("jobs.inputs"), children: <pre className="tr-job-detail">{JSON.stringify(detail.artifacts ?? detail.inputs ?? [], null, 2)}</pre> },
            ]}
          />
        </>) : <p>{t("loading")}</p>}
      </Drawer>
      <TRDataTable<JobRow>
        rowKey={(row) => row.job_id || JSON.stringify(row)}
        columns={columns}
        rows={jobs}
        loading={loading}
        error={error}
        pagination={{
          page, pageSize, total,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage);
            setPageSize(nextSize);
          },
        }}
      />
    </section>
  );
}
