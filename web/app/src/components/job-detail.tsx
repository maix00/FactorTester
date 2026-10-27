import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Progress, Select, Spin, Tabs, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { jobURL, progressPercent, terminalStatus, type JobReference } from "../job-model.ts";
import { usePageInstance } from "../page-instance.ts";
import { readJobArtifact } from "../artifacts.ts";
import { ResultView } from "./result-view.tsx";

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
  const blobURL = useRef("");
  const [artifactName, setArtifactName] = useState("");
  const [artifactURL, setArtifactURL] = useState("");
  useEffect(() => () => { artifactRequest.current?.abort(); if (blobURL.current) URL.revokeObjectURL(blobURL.current); }, []);
  const artifact = async (name: string, download = false): Promise<void> => {
    artifactRequest.current?.abort(); const controller = new AbortController(); artifactRequest.current = controller;
    try {
      const blob = await readJobArtifact(job, name, controller.signal); if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      if (download) { const link = document.createElement("a"); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
      else { if (blobURL.current) URL.revokeObjectURL(blobURL.current); blobURL.current = url; setArtifactURL(url); setArtifactName(name); }
    } catch (reason) { if (!controller.signal.aborted) setError(String((reason as Error).message)); }
  };
  useEffect(() => {
    if (instance.active === false || !job.job_id) return;
    const controller = new AbortController(); let stream: EventSource | undefined; let fallback: ReturnType<typeof setTimeout> | undefined;
    artifactRequest.current?.abort(); if (blobURL.current) URL.revokeObjectURL(blobURL.current); blobURL.current = ""; setArtifactURL(""); setArtifactName("");
    setDetail(null); setError(""); setResult(null); setArtifacts([]); setProgress(null);
    const loadOutputs = async (): Promise<void> => {
      const values = await Promise.allSettled([request(jobURL(job, "/result"), { signal: controller.signal }), request(jobURL(job, "/artifacts"), { signal: controller.signal })]);
      if (controller.signal.aborted) return;
      if (values[0].status === "fulfilled") setResult(values[0].value.result ?? values[0].value);
      if (values[1].status === "fulfilled") setArtifacts(values[1].value.artifacts ?? values[1].value.items ?? []);
    };
    const load = async (): Promise<boolean> => {
      const data = await request(jobURL(job), { signal: controller.signal });
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
  }, [job.job_id, job.server_id, job.service_port, refresh, instance.active]);
  if (!job.job_id) return <Empty description={t("empty")} />;
  if (error) return <Alert type="error" showIcon message={error} action={<Button onClick={() => setRefresh((value) => value + 1)}>{t("retry")}</Button>} />;
  if (!detail) return <Spin />;
  const percent = progressPercent(progress, detail.status);
  return <div className="tr-job-page-detail"><div className="tr-job-state"><Tag color={detail.status === "succeeded" ? "green" : detail.status === "failed" ? "red" : "blue"}>{t(`jobs.states.${detail.status}`, { defaultValue: detail.status })}</Tag>
    {percent !== undefined ? <Progress percent={percent} showInfo status={detail.status === "failed" ? "exception" : !terminalStatus(detail.status) ? "active" : "normal"} /> : null}
    <span>{String(progress?.phase || progress?.message || "")}</span>
    {!terminalStatus(detail.status) ? <Button danger onClick={() => { void request(jobURL(job, "/cancel"), { method: "POST" }).then(() => setRefresh((value) => value + 1)).catch((reason) => setError(reason.message)); }}>{t("jobs.cancel")}</Button> : null}</div>
    {detail.error ? <Alert type="error" showIcon message={typeof detail.error === "string" ? detail.error : JSON.stringify(detail.error)} /> : null}
    <Tabs items={[
      { key: "overview", label: t("jobs.overview"), children: <ResultView value={{ job_id: detail.job_id || job.job_id, kind: detail.kind, status: detail.status, ...detail.result_summary }} /> },
      { key: "results", label: t("jobs.results"), children: result ? <ResultView value={result} /> : <Empty description={t(terminalStatus(detail.status) ? "empty" : "jobs.waitingResults")} /> },
      { key: "configuration", label: t("jobs.configuration"), children: <pre className="tr-job-detail">{JSON.stringify(detail.execution_plan || detail.run_spec || detail.job_spec || detail.configuration, null, 2)}</pre> },
      { key: "inputs", label: t("jobs.inputs"), children: <div className="tr-job-artifact-list">{artifacts.map((item, index) => {
        const name = String(item.name || "");
        return <div className="tr-job-artifact" key={item.name || index}><span>{item.name || item.kind}</span>{name ? <Button type="link" onClick={() => void artifact(name, true)}>{t("jobs.download")}</Button> : null}</div>;
      })}{!artifacts.length ? <Empty description={t("empty")} /> : null}</div> },
      { key: "outputs", label: t("jobs.output"), children: <><Select aria-label={t("jobs.output")} style={{ width: "100%" }} value={artifactName || undefined} options={artifacts.filter((item) => /\.html?$/i.test(item.name || "")).map((item) => ({ label: item.name, value: item.name }))} onChange={(name) => void artifact(name)} />
        {artifactURL ? <iframe className="tr-artifact-frame" title={t("jobs.output")} src={artifactURL} sandbox="allow-scripts allow-downloads" /> : null}</> },
    ]} /></div>;
}
