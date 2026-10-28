import React, { useEffect, useState } from "react";
import { Alert, Button, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { readJobArtifact } from "../artifacts.ts";
import type { JobReference } from "../job-model.ts";

/** One authorized artifact, loaded only while its result tab is mounted. */
export function JobHtmlReport({ job, name }: { job: JobReference; name?: string }): React.ReactElement {
  const { t } = useTranslation();
  const [url, setURL] = useState(""), [error, setError] = useState(""), [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let objectURL = "";
    setURL(""); setError(""); setLoading(Boolean(name));
    if (name) void readJobArtifact(job, name, controller.signal).then(blob => {
      if (controller.signal.aborted) return;
      objectURL = URL.createObjectURL(blob); setURL(objectURL);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); if (objectURL) URL.revokeObjectURL(objectURL); };
  }, [job.job_id, job.server_id, job.service_port, job.execution_node_id, name, reload]);
  if (!name) return <Empty description={t("empty")} />;
  if (error) return <Alert type="error" message={error} action={<Button onClick={() => setReload(value => value + 1)}>{t("retry")}</Button>} />;
  if (loading || !url) return <div role="status"><Spin /></div>;
  return <iframe className="tr-artifact-frame" title={name} src={url} sandbox="allow-scripts allow-downloads" />;
}
