import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { formatDate } from "../format.ts";

type Research = { research_id?: string; title?: string; visibility?: string; updated_at?: string; owner?: string };
type Report = { publication_id?: string; report_id?: string; title?: string; summary?: string; updated_at?: string };

export function ResearchPage(): React.ReactElement {
  const { t } = useTranslation();
  const [items, setItems] = useState<Research[]>([]);
  const [selected, setSelected] = useState<Research | null>(null);
  const [legacy, setLegacy] = useState(false);
  const [tab, setTab] = useState<"researches" | "reports">("researches");
  const [reports, setReports] = useState<Report[]>([]);
  const [reportID, setReportID] = useState<string>("");
  const [reportContent, setReportContent] = useState<string>("");

  useEffect(() => {
    fetch("/api/research?scope=all", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { researches?: Research[]; items?: Research[] }) => setItems(payload.researches ?? payload.items ?? []))
      .catch((error: Error) => notify({ code: "research.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [t]);

  useEffect(() => {
    if (tab !== "reports") return;
    fetch("/api/research/reports?scope=all", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { reports?: Report[]; items?: Report[] }) => setReports(payload.reports ?? payload.items ?? []))
      .catch((error: Error) => notify({ code: "research.reports", type: "error", message: t("loadFailed"), description: error.message }));
  }, [tab, t]);

  useEffect(() => {
    if (!reportID) { setReportContent(""); return; }
    fetch(`/api/research-reports/${encodeURIComponent(reportID)}/agent.md`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setReportContent(value))
      .catch((error: Error) => notify({ code: "research.report", type: "error", message: t("loadFailed"), description: error.message }));
  }, [reportID, t]);

  return (
    <section className="tr-research-page">
      <header>
        <div><h1>{t("nav.research")}</h1><p>{t("research.hint")}</p></div>
        <button type="button" className="tr-toolbar-button" onClick={() => setLegacy(true)}>{t("research.legacy")}</button>
      </header>
      <div className="tr-catalog-tabs">
        <button type="button" className={tab === "researches" ? "is-active" : ""} onClick={() => setTab("researches")}>{t("research.tabResearches")}</button>
        <button type="button" className={tab === "reports" ? "is-active" : ""} onClick={() => setTab("reports")}>{t("research.tabReports")}</button>
      </div>
      {tab === "reports" ? (
        <div className="tr-research-list">
          {reports.length === 0 ? <p>{t("empty")}</p> : reports.map((report, index) => {
            const id = String(report.publication_id ?? report.report_id ?? index);
            return <button key={id} type="button" onClick={() => setReportID(id)}><b>{report.title ?? id}</b><span>{report.summary ?? ""}</span></button>;
          })}
        </div>
      ) : (
      <div className="tr-research-list">
        {items.length === 0 ? <p>{t("empty")}</p> : items.map((item) => (
          <button key={item.research_id ?? item.title} type="button" onClick={() => setSelected(item)}>
            <b>{item.title ?? item.research_id}</b>
            <span>{item.visibility ?? ""}</span>
            <small>{item.owner ?? ""}{item.updated_at ? ` · ${formatDate(item.updated_at, { dateStyle: "medium" })}` : ""}</small>
          </button>
        ))}
      </div>)}
      {reportID ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={reportID}>
          <div className="tr-legacy-bar"><strong>{reportID}</strong><button type="button" onClick={() => setReportID("")}>{t("notifications.close")}</button></div>
          <pre className="tr-job-detail">{reportContent || t("loading")}</pre>
        </div>
      ) : null}
      {legacy ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={t("research.legacy")}>
          <div className="tr-legacy-bar"><strong>{t("research.legacy")}</strong><button type="button" onClick={() => setLegacy(false)}>{t("notifications.close")}</button></div>
          <iframe title={t("research.legacy")} src="/research?section=researches&presentation=embedded" />
        </div>
      ) : null}
      {selected ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={selected.title ?? selected.research_id}>
          <div className="tr-legacy-bar"><strong>{selected.title ?? selected.research_id}</strong><button type="button" onClick={() => setSelected(null)}>{t("notifications.close")}</button></div>
          <iframe title={selected.title ?? "research"} src={`/researches/${encodeURIComponent(selected.research_id ?? "")}?presentation=embedded`} />
        </div>
      ) : null}
    </section>
  );
}
