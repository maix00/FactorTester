import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { formatDate } from "../format.ts";

type Job = { job_id?: string; status?: string; task_name?: string; updated_at?: string };

export function MobileJobsPage(): React.ReactElement {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const limit = 20;

  const load = (next: number): void => {
    setLoading(true);
    fetch(`/api/jobs?page=${next}&limit=${limit}`, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        const rows: Job[] = payload.items ?? payload.jobs ?? [];
        setJobs((existing) => next === 1 ? rows : [...existing, ...rows]);
        setTotal(Number(payload.total ?? rows.length));
        setPage(next);
        setError("");
      })
      .catch((reason: Error) => {
        setError(reason.message);
        notify({ code: "mobile.jobs.load", type: "error", message: t("loadFailed"), description: reason.message });
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(1); }, []);

  return (
    <section className="tr-mobile-jobs">
      <header><h1>{t("nav.jobs")}</h1><p>{t("total", { count: total })}</p></header>
      {error ? <div className="tr-mobile-jobs-error">{t("loadFailed")}</div> : null}
      <div className="tr-mobile-job-list">
        {jobs.map((job, index) => (
          <article className="tr-mobile-job-card" key={job.job_id ?? index}>
            <div className="tr-mobile-job-top">
              <strong>{job.task_name || job.job_id || "—"}</strong>
              <span className={`tr-mobile-job-status is-${job.status ?? "unknown"}`}>{job.status || "—"}</span>
            </div>
            <small>{job.job_id || "—"}</small>
            {job.updated_at ? <small>{formatDate(job.updated_at, { dateStyle: "medium", timeStyle: "short" })}</small> : null}
          </article>
        ))}
      </div>
      {!loading && jobs.length === 0 && !error ? <p className="tr-mobile-jobs-empty">{t("empty")}</p> : null}
      {jobs.length < total ? (
        <button type="button" className="tr-mobile-load-more" disabled={loading} onClick={() => load(page + 1)}>
          {loading ? t("loading") : t("more")}
        </button>
      ) : null}
    </section>
  );
}
