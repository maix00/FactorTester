import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Select, Tabs, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { FunctionPage } from "../components/function-page.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { JobDetail } from "../components/job-detail.tsx";
import { request } from "../configuration/api.ts";
import { usePageInstance } from "../page-instance.ts";
import type { JobReference } from "../job-model.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { JobFeed, type JobScope } from "../job-feed.ts";
import { formatDate } from "../format.ts";
export function JobsPage(): React.ReactElement {
  const { t } = useTranslation(); const instance = usePageInstance(); const mobile = useCompactLayout();
  const [rows, setRows] = useState<any[]>([]), [page, setPage] = useState(1), [size, setSize] = useState(20), [total, setTotal] = useState(0);
  const [actualPage, setActualPage] = useState(1), [hasMore, setHasMore] = useState(false);
  const [scope, setScope] = useState<JobScope>("server"), [username, setUsername] = useState("");
  const [users, setUsers] = useState<{ username: string }[]>([]), [loginRequired, setLoginRequired] = useState(false);
  const feed = useRef({ key: "", reader: new JobFeed() });
  const [loading, setLoading] = useState(false), [error, setError] = useState(""), [revision, setRevision] = useState(0);
  useEffect(() => {
    if (instance.active === false) return;
    const controller = new AbortController(); setLoading(true); setError("");
    const key = JSON.stringify([scope, username, size, revision]);
    if (feed.current.key !== key) feed.current = { key, reader: new JobFeed() };
    feed.current.reader.read(request, { scope, username, page, size, signal: controller.signal }).then((data) => {
      if (controller.signal.aborted) return;
      setRows(data.jobs ?? data.items ?? []); setTotal(data.total || 0); setUsers(data.users || []); setLoginRequired(!!data.requires_login);
      setActualPage(data.page || page); setHasMore(!!data.has_more);
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, size, scope, username, revision, instance.active]);
  const scopes = ["server", "cross-server", "mine", "subordinates"].map((key) => ({ key, value: key, label: t(`jobs.scopes.${key}`) }));
  const changeScope = (value: string): void => { setScope(value as JobScope); setPage(1); setActualPage(1); setUsername(""); setRows([]); setUsers([]); };
  return <FunctionPage title={t("nav.jobs")} actions={<Button onClick={() => setRevision((value) => value + 1)}>{t("configuration.reload")}</Button>}>
    {mobile ? <div className="tr-page-filters"><Select aria-label={t("jobs.scope")} value={scope} options={scopes} onChange={changeScope} /></div> : <Tabs activeKey={scope} onChange={changeScope} items={scopes} />}
    {scope === "subordinates" ? <div className="tr-page-filters"><Select aria-label={t("jobs.subordinate")} placeholder={t("jobs.subordinate")} value={username || undefined} options={users.map((user) => ({ value: user.username, label: user.username }))} onChange={(value) => { setUsername(value); setPage(1); }} /></div> : null}
    {loginRequired ? <Alert type="info" message={t("jobs.loginRequired")} /> : null}
    <TRDataTable rows={rows} rowKey={(row) => `${row.server_id || ""}:${row.port || row.service_port || ""}:${row.job_id}`} loading={loading} error={error} pagination={{ page: scope === "server" ? actualPage : page, mode: scope === "server" ? "cursor" : undefined, hasMore, pageSize: size, total, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("jobs.task"), key: "task", render: (_, row) => <button className="tr-table-link" onClick={() => instance.open("job-detail", { jobId: row.job_id, serverId: row.server_id, servicePort: row.port || row.service_port })}>{row.task_name || row.kind || row.job_id}{mobile ? <small className="tr-job-mobile-meta" title={row.job_id}>{[row.server_name || row.server_id, row.port || row.service_port, row.job_id].filter(Boolean).join(" · ")}</small> : null}</button> },
      { title: t("jobs.status"), dataIndex: "status", render: (value) => <Tag>{t(`jobs.states.${value}`, { defaultValue: value })}</Tag> },
      { title: t("jobs.updated"), dataIndex: "updated_at", responsive: ["md"], render: (value) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
      { title: t("jobs.server"), key: "server", responsive: ["md"], render: (_, row) => row.server_name || row.server_id || "—" },
      { title: t("jobs.port"), key: "port", responsive: ["md"], render: (_, row) => row.port || row.service_port || "—" },
      { title: "Profile", key: "profile", responsive: ["lg"], render: (_, row) => row.profile_name || row.profile_id || "—" },
      { title: t("jobs.jobId"), dataIndex: "job_id", responsive: ["md"], ellipsis: true },
    ]} />
  </FunctionPage>;
}
export function JobDetailPage(): React.ReactElement {
  const { t } = useTranslation(); const instance = usePageInstance();
  return <FunctionPage title={t("jobs.detail")}><JobDetail job={{ job_id: instance.args.jobId || "", server_id: instance.args.serverId, service_port: instance.args.servicePort } as JobReference} /></FunctionPage>;
}
