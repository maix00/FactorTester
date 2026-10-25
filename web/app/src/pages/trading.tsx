import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";

type Family = { id?: string; family_id?: string; title?: string; name?: string; description?: string };
type Payload = { families?: Family[] };

export function TradingPage(): React.ReactElement {
  const { t } = useTranslation();
  const [families, setFamilies] = useState<Family[]>([]);
  const [family, setFamily] = useState<string>("");
  const [legacy, setLegacy] = useState(false);
  const [legacyRoute, setLegacyRoute] = useState("/backtest?presentation=embedded");
  const [legacyTitle, setLegacyTitle] = useState("");

  useEffect(() => {
    const fallback = [
      { id: "threshold", title: t("trading.familyThreshold"), description: t("trading.familyThresholdHint") },
      { id: "cross_sectional_group", title: t("trading.familyGroup"), description: t("trading.familyGroupHint") },
    ];
    fetch("/api/strategy-families", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: Payload) => setFamilies(payload.families?.length ? payload.families : fallback))
      .catch(() => setFamilies(fallback));
  }, [t]);

  const openLegacy = (route: string, title: string): void => {
    setLegacyRoute(`${route}?presentation=embedded`);
    setLegacyTitle(title);
    setLegacy(true);
  };
  const open = (id: string): void => {
    setFamily(id);
    setLegacyRoute(`/backtest?presentation=embedded&family=${encodeURIComponent(id)}`);
    setLegacyTitle(t("trading.legacy"));
    setLegacy(true);
  };
  return (
    <section className="tr-trading-page">
      <header><div><h1>{t("nav.trading")}</h1><p>{t("trading.hint")}</p></div></header>
      <div className="tr-trading-tests">
        <button type="button" onClick={() => openLegacy("/ic", t("trading.ic"))}>{t("trading.ic")}</button>
        <button type="button" onClick={() => openLegacy("/factor-series", t("trading.factorSeries"))}>{t("trading.factorSeries")}</button>
      </div>
      <div className="tr-trading-families">
        {families.length === 0 ? <p>{t("empty")}</p> : families.map((item) => {
          const id = String(item.id ?? item.family_id ?? item.name ?? "");
          return (
            <article key={id}>
              <b>{item.title ?? item.name ?? id}</b>
              <p>{item.description ?? ""}</p>
              <button type="button" className="tr-toolbar-button" onClick={() => open(id)}>{t("trading.open")}</button>
            </article>
          );
        })}
      </div>
      {legacy ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={t("trading.legacy")}>
          <div className="tr-legacy-bar"><strong>{legacyTitle || t("trading.legacy")}</strong><button type="button" onClick={() => setLegacy(false)}>{t("notifications.close")}</button></div>
          <iframe title={legacyTitle || t("trading.legacy")} src={legacyRoute} />
        </div>
      ) : null}
    </section>
  );
}
