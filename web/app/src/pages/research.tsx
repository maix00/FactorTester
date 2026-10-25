import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { formatDate } from "../format.ts";

type Research = { research_id?: string; title?: string; visibility?: string; updated_at?: string; owner?: string };

export function ResearchPage(): React.ReactElement {
  const { t } = useTranslation();
  const [items, setItems] = useState<Research[]>([]);
  const [selected, setSelected] = useState<Research | null>(null);
  const [legacy, setLegacy] = useState(false);

  useEffect(() => {
    fetch("/api/research?scope=all", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { researches?: Research[]; items?: Research[] }) => setItems(payload.researches ?? payload.items ?? []))
      .catch((error: Error) => notify({ code: "research.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [t]);

  return (
    <section className="tr-research-page">
      <header>
        <div><h1>{t("nav.research")}</h1><p>{t("research.hint")}</p></div>
        <button type="button" className="tr-toolbar-button" onClick={() => setLegacy(true)}>{t("research.legacy")}</button>
      </header>
      <div className="tr-research-list">
        {items.length === 0 ? <p>{t("empty")}</p> : items.map((item) => (
          <button key={item.research_id ?? item.title} type="button" onClick={() => setSelected(item)}>
            <b>{item.title ?? item.research_id}</b>
            <span>{item.visibility ?? ""}</span>
            <small>{item.owner ?? ""}{item.updated_at ? ` · ${formatDate(item.updated_at, { dateStyle: "medium" })}` : ""}</small>
          </button>
        ))}
      </div>
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
