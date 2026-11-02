import React, { useEffect, useState } from "react";
import { Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { reportExportURL, type ReportExportTarget } from "../report-export.ts";
import { notify } from "../notifications/core.ts";

export function ReportMarkdown({ target }: { target: ReportExportTarget }): React.ReactElement {
  const { t } = useTranslation();
  const url = reportExportURL(target,"md");
  const [open, setOpen] = useState(false), [value, setValue] = useState<string | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false), [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setValue(null); setError(""); setLoading(true);
    if (!url) { setError(t("report.exportMissingSource")); setLoading(false); return () => controller.abort(); }
    void fetch(url, { credentials: "same-origin", signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text(); })
      .then(text => { if (!controller.signal.aborted) setValue(text); })
      .catch(reason => { if (!controller.signal.aborted) {const description = reason instanceof Error ? reason.message : String(reason);setError(description);notify({code:"report.markdown.load.failed",type:"error",message:t("loadFailed"),description});} })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, url, revision]);
  return <details className="tr-report-markdown" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{t("report.markdown")}</summary>
    {loading ? <Spin tip={t("loading")} /> : null}
    {error ? <Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button> : null}
    {value !== null ? <><Button onClick={() => setRevision(value => value + 1)}>{t("configuration.reload")}</Button><pre className="tr-job-detail">{value || t("empty")}</pre></> : null}
  </details>;
}
