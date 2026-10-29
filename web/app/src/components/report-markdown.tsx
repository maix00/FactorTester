import React, { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";

export function ReportMarkdown({ publicationID }: { publicationID: string }): React.ReactElement {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false), [value, setValue] = useState<string | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false), [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setValue(null); setError(""); setLoading(true);
    void fetch(`/api/research-reports/${encodeURIComponent(publicationID)}/agent.md`, { credentials: "same-origin", signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text(); })
      .then(text => { if (!controller.signal.aborted) setValue(text); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, publicationID, revision]);
  return <details className="tr-report-markdown" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{t("report.markdown")}</summary>
    {loading ? <Spin tip={t("loading")} /> : null}
    {error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : null}
    {value !== null ? <><Button onClick={() => setRevision(value => value + 1)}>{t("configuration.reload")}</Button><pre className="tr-job-detail">{value || t("empty")}</pre></> : null}
  </details>;
}
