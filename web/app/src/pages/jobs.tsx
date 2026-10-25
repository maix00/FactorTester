import React, { useEffect, useState } from "react";

type JobRow = {
  job_id?: string;
  status?: string;
  task_name?: string;
  updated_at?: string;
  kind?: string;
};

export function JobsPage(): React.ReactElement {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/jobs?limit=20", { credentials: "same-origin" })
      .then(async (response) => {
        const value = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
        return value;
      })
      .then((value) => {
        if (!cancelled) setJobs(Array.isArray(value.jobs) ? value.jobs : []);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <p className="tr-page-placeholder">正在读取运行记录…</p>;
  if (error) return <p className="tr-page-error" role="alert">读取运行记录失败：{error}</p>;
  if (!jobs.length) return <p className="tr-page-placeholder">暂无运行记录。</p>;

  return (
    <section className="tr-panel">
      <header className="tr-panel-header">
        <h2>最近运行</h2>
        <span>{jobs.length} 条</span>
      </header>
      <div className="tr-job-list">
      {jobs.map((job, index) => (
        <a className="tr-job-row" key={job.job_id || index} href={`/jobs/${encodeURIComponent(job.job_id || "")}`}>
          <span className="tr-job-title">{job.task_name || job.kind || job.job_id || "运行"}</span>
          <span className={`tr-job-status is-${String(job.status || "unknown").toLowerCase()}`}>{job.status || "unknown"}</span>
          <span className="tr-job-id">{job.job_id || ""}</span>
        </a>
      ))}
      </div>
    </section>
  );
}
