import React, { useEffect, useState } from "react";
import { Tag, Typography } from "antd";
import type { TableProps } from "antd";
import { useTranslation } from "react-i18next";
import { TRDataTable } from "../components/data-table.tsx";
import { TRMultiSelectFilter } from "../components/multi-select.tsx";

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

  const columns: TableProps<JobRow>["columns"] = [
    {
      title: t("jobs.task"),
      dataIndex: "task_name",
      key: "task",
      ellipsis: true,
      render: (value: string, row) => (
        <a href={`/jobs/${encodeURIComponent(row.job_id || "")}`} className="tr-table-link">
          {value || row.kind || row.job_id || "运行"}
        </a>
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
