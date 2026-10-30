import React, { useRef, useState } from "react";
import { Button, Dropdown } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { reportExportName, reportExportPayload, reportExportURL, type ReportExportFormat, type ReportExportTarget } from "../report-export.ts";

export function ReportExport({ target }: { target: ReportExportTarget }): React.ReactElement {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const handler = (window as unknown as {webkit?: {messageHandlers?: {researchReportExport?: {postMessage?: (value: unknown) => void}}}}).webkit?.messageHandlers?.researchReportExport;
  const run = async (format: ReportExportFormat): Promise<void> => {
    if (pending.current) return;
    const url = reportExportURL(target, format);
    if (!url) { notify({code:"report.export.address",type:"error",message:t("report.exportMissingSource")}); return; }
    if (typeof handler?.postMessage === "function") {
      try { handler.postMessage(reportExportPayload(target, format)); }
      catch (reason) { notify({code:"report.export.failed",type:"error",message:t("report.exportFailed"),description:reason instanceof Error ? reason.message : String(reason)}); }
      return;
    }
    pending.current = true; setBusy(true);
    try {
      const response = await fetch(url, {credentials:"same-origin"});
      if (!response.ok) { const value = await response.json().catch(() => ({})); throw new Error(value.error || `HTTP ${response.status}`); }
      const objectURL = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = objectURL; anchor.download = reportExportName(target.title, format); document.body.append(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
    } catch (reason) { notify({code:"report.export.failed",type:"error",message:t("report.exportFailed"),description:reason instanceof Error ? reason.message : String(reason)}); }
    finally { pending.current = false; setBusy(false); }
  };
  return <Dropdown trigger={["click"]} disabled={busy} menu={{items:[{key:"md",label:t("report.exportMarkdown")},{key:"pdf",label:typeof handler?.postMessage === "function" ? t("report.exportPDF") : t("report.exportPDFRequiresClient"),disabled:typeof handler?.postMessage !== "function"}],onClick:({key}) => { if (key === "md" || key === "pdf") void run(key); }}}>
    <Button style={{justifySelf:"start"}} icon={<DownloadOutlined />} loading={busy}>{t("report.export")}</Button>
  </Dropdown>;
}
