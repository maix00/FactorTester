import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Progress, Select, Spin, Tabs, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { jobURL, jobDetailOf, progressPercent, terminalStatus, type JobReference } from "../job-model.ts";
import { usePageInstance } from "../page-instance.ts";
import { readJobArtifact } from "../artifacts.ts";
import { FactorResults } from "./factor-results.tsx";
import { seriesArtifact } from "../charts/factor-result.ts";
import { FrozenRunSpec } from "./frozen-run-spec.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { ResultView } from "./result-view.tsx";
import { JobHtmlReport } from "./job-html-report.tsx";

export function JobDetail({ job }: { job: JobReference }): React.ReactElement {
  const { t } = useTranslation();
  const instance = usePageInstance();
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [progress, setProgress] = useState<Record<string, unknown> | null>(null);
  const [result, setResult] = useState<unknown>(null);
  const [artifacts, setArtifacts] = useState<Record<string, any>[]>([]);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const artifactRequest = useRef<AbortController | null>(null);
  const [artifactName, setArtifactName] = useState("");
  useEffect(() => () => artifactRequest.current?.abort(), []);
  const downloadArtifact = async (name: string): Promise<void> => {
    artifactRequest.current?.abort(); const controller = new AbortController(); artifactRequest.current = controller;
    try {
      const blob = await readJobArtifact(job, name, controller.signal); if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) { if (!controller.signal.aborted) setError(String((reason as Error).message)); }
  };
  useEffect(() => {
    if (instance.active === false || !job.job_id) return;
    const controller = new AbortController(); let stream: EventSource | undefined; let fallback: ReturnType<typeof setTimeout> | undefined;
    artifactRequest.current?.abort(); setArtifactName("");
    setDetail(null); setError(""); setResult(null); setArtifacts([]); setProgress(null);
    const loadOutputs = async (): Promise<void> => {
      const values = await Promise.allSettled([request(jobURL(job, "/result"), { signal: controller.signal }), request(jobURL(job, "/artifacts"), { signal: controller.signal })]);
      if (controller.signal.aborted) return;
      if (values[0].status === "fulfilled") setResult(values[0].value.result ?? values[0].value);
      if (values[1].status === "fulfilled") setArtifacts(values[1].value.artifacts ?? values[1].value.items ?? []);
    };
    const load = async (): Promise<boolean> => {
      const data = jobDetailOf(await request(jobURL(job), { signal: controller.signal }));
      if (controller.signal.aborted) return true;
      setDetail(data); setProgress(data.progress || null);
      if (terminalStatus(data.status)) { stream?.close(); if (data.status === "succeeded") await loadOutputs(); }
      return terminalStatus(data.status);
    };
    void load().then((done) => {
      if (controller.signal.aborted || done) return;
      stream = new EventSource(jobURL(job, "/stream"), { withCredentials: true });
      const update = (event: MessageEvent): void => {
        if (controller.signal.aborted) return;
        try {
          const data = JSON.parse(event.data);
          if (data.latest_progress) setProgress(data.latest_progress);
          else if (data.percent !== undefined || data.completed !== undefined) setProgress(data);
          if (data.status) setDetail((old) => ({ ...old, status: data.status }));
          if (terminalStatus(data.status)) { stream?.close(); void load().catch((reason) => { if (!controller.signal.aborted) setError(String(reason.message || reason)); }); }
        } catch { /* a malformed transport frame is not a result */ }
      };
      stream.addEventListener("progress", update as EventListener);
      stream.addEventListener("heartbeat", update as EventListener);
      stream.addEventListener("result", update as EventListener);
      stream.onerror = () => {
        stream?.close();
        const poll = (): void => { void load().then((done) => { if (!controller.signal.aborted && !done) fallback = setTimeout(poll, 3000); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }); };
        fallback = setTimeout(poll, 3000);
      };
    }).catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => { controller.abort(); stream?.close(); clearTimeout(fallback); };
  }, [job.job_id, job.server_id, job.service_port, job.execution_node_id, refresh, instance.active]);
  if (!job.job_id) return <Empty description={t("empty")} />;
  if (error) return <Alert type="error" showIcon message={error} action={<Button onClick={() => setRefresh((value) => value + 1)}>{t("retry")}</Button>} />;
  if (!detail) return <Spin />;
  const percent = progressPercent(progress, detail.status);
  return <div className="tr-job-page-detail"><div className="tr-job-state"><Tag color={detail.status === "succeeded" ? "green" : detail.status === "failed" ? "red" : "blue"}>{t(`jobs.states.${detail.status}`, { defaultValue: detail.status })}</Tag>
    {percent !== undefined ? <Progress percent={percent} showInfo status={detail.status === "failed" ? "exception" : !terminalStatus(detail.status) ? "active" : "normal"} /> : null}
    {progress?.phase || progress?.message ? <span className="tr-job-phase">{String(progress.phase || progress.message)}</span> : null}
    {!terminalStatus(detail.status) ? <Button danger onClick={() => { void request(jobURL(job, "/cancel"), { method: "POST" }).then(() => setRefresh((value) => value + 1)).catch((reason) => setError(reason.message)); }}>{t("jobs.cancel")}</Button> : null}</div>
    {detail.error ? <Alert type="error" showIcon message={typeof detail.error === "string" ? detail.error : JSON.stringify(detail.error)} /> : null}
    <Tabs destroyOnHidden items={[
      { key: "overview", label: t("jobs.overview"), children: <><PropertyGroups groups={[{key:"job",title:t("jobs.overview"),items:[
        {key:"job",label:t("jobs.jobId"),value:detail.job_id || job.job_id},
        {key:"kind",label:t("configuration.testKind"),value:detail.kind,render:value => t(`configuration.analysisNames.${value}`,{defaultValue:String(value)})},
        {key:"status",label:t("jobs.status"),value:detail.status,render:value => t(`jobs.states.${value}`,{defaultValue:String(value)})},
        {key:"server",label:t("jobs.server"),value:detail.server_name || detail.server_id || job.server_id},
        {key:"port",label:t("jobs.port"),value:detail.port ?? detail.service_port ?? job.service_port},
      ]}]} />{detail.result_summary ? <ResultView value={detail.result_summary} /> : null}</> },
      { key: "results", label: t("jobs.results"), children: detail.kind === "backtest" && artifacts.some(item=>item.name==="tearsheet.html") ? <JobHtmlReport job={job} name="tearsheet.html" /> : detail.kind === "factor_evaluation" ? <FactorResults result={result || detail.result_summary} artifactName={seriesArtifact(artifacts, true)} job={job} configuration={detail.configuration || detail.run_spec || detail.job_spec} /> : seriesArtifact(artifacts) ? <Tabs items={[
        { key: "summary", label: t("jobs.overview"), children: <ResultView value={result} /> },
        { key: "factor-series", label: t("factorResults.title"), children: <FactorResults result={null} artifactName={seriesArtifact(artifacts)} job={job} configuration={detail.configuration || detail.run_spec || detail.job_spec} /> },
      ]} /> : result ? <ResultView value={result} /> : <Empty description={t(terminalStatus(detail.status) ? "empty" : "jobs.waitingResults")} /> },
      { key: "configuration", label: t("jobs.configuration"), children: <FrozenRunSpec hash={detail.run_spec_hash} serverID={job.server_id} /> },
      { key: "inputs", label: t("jobs.inputs"), children: <div className="tr-job-artifact-list">{artifacts.map((item, index) => {
        const name = String(item.name || "");
        return <div className="tr-job-artifact" key={item.name || index}><span>{item.name || item.kind}</span>{name ? <Button type="link" onClick={() => void downloadArtifact(name)}>{t("jobs.download")}</Button> : null}</div>;
      })}{!artifacts.length ? <Empty description={t("empty")} /> : null}</div> },
      { key: "outputs", label: t("jobs.output"), children: <><Select aria-label={t("jobs.output")} style={{ width: "100%" }} value={artifactName || undefined} options={artifacts.filter((item) => /\.html?$/i.test(item.name || "")).map((item) => ({ label: item.name, value: item.name }))} onChange={setArtifactName} />
        {artifactName ? <JobHtmlReport job={job} name={artifactName} /> : null}</> },
    ]} /></div>;
}
