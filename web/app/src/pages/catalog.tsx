import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";

type Group = { id?: string; name?: string; title?: string; description?: string; member_count?: number; product_count?: number };
type Product = { id?: string; name?: string; title?: string; data_source?: string };
type Payload<T> = { groups?: T[]; products?: T[]; sources?: { id: string; name?: string }[] };

export function CatalogPage(): React.ReactElement {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<Group[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [legacy, setLegacy] = useState(false);
  const [tab, setTab] = useState<"products" | "factors" | "strategies">("products");
  const [strategies, setStrategies] = useState<Record<string, unknown>[]>([]);
  const [strategyPage, setStrategyPage] = useState(1);
  const [strategyTotal, setStrategyTotal] = useState(0);
  const [strategyDetail, setStrategyDetail] = useState<string>("");
  const [strategyData, setStrategyData] = useState<Record<string, unknown> | null>(null);
  const [factors, setFactors] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    fetch("/api/product-library/product-groups?view=summary", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: Payload<Group>) => setGroups(payload.groups ?? []))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [t]);

  useEffect(() => {
    if (tab !== "strategies") return;
    setLoading(true);
    fetch(`/api/strategy-library/strategies?scope=all&page=${strategyPage}&limit=20`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { items?: Record<string, unknown>[]; total?: number }) => {
        setStrategies((current) => strategyPage === 1 ? payload.items ?? [] : [...current, ...(payload.items ?? [])]);
        setStrategyTotal(Number(payload.total ?? 0));
      })
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [tab, strategyPage, t]);

  useEffect(() => {
    if (!strategyDetail) { setStrategyData(null); return; }
    setStrategyData(null);
    fetch(`/api/strategy-library/strategies/${encodeURIComponent(strategyDetail)}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setStrategyData(value))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [strategyDetail, t]);

  useEffect(() => {
    if (tab !== "factors") return;
    setLoading(true);
    fetch("/api/factor-library/factors", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { factors?: Record<string, unknown>[] }) => setFactors(payload.factors ?? []))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [tab, t]);

  useEffect(() => {
    if (tab !== "products") return;
    setLoading(true);
    const query = selected ? `?group_ref=${encodeURIComponent(selected)}` : "";
    fetch(`/api/product-library/products${query}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: Payload<Product>) => setProducts(payload.products ?? []))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [selected, tab, t]);

  return (
    <section className="tr-catalog-page">
      <header>
        <div><h1>{t("nav.catalog")}</h1><p>{t("catalog.hint")}</p></div>
        <button type="button" className="tr-toolbar-button" onClick={() => setLegacy(true)}>{t("catalog.legacy")}</button>
      </header>
      <div className="tr-catalog-tabs">
        <button type="button" className={tab === "products" ? "is-active" : ""} onClick={() => setTab("products")}>{t("catalog.products")}</button>
        <button type="button" className={tab === "factors" ? "is-active" : ""} onClick={() => setTab("factors")}>{t("catalog.factors")}</button>
        <button type="button" className={tab === "strategies" ? "is-active" : ""} onClick={() => { setTab("strategies"); setStrategyPage(1); }}>{t("catalog.strategies")}</button>
      </div>
      {tab === "products" ? <div className="tr-catalog-groups">
        <button type="button" className={selected ? "" : "is-active"} onClick={() => setSelected("")}>{t("catalog.all")}</button>
        {groups.map((group) => {
          const id = String(group.id ?? group.name ?? "");
          return (
            <button key={id} type="button" className={selected === id ? "is-active" : ""} onClick={() => setSelected(id)}>
              <b>{group.name ?? group.title ?? id}</b>
              <small>{group.member_count ?? group.product_count ?? 0} {t("catalog.members")}</small>
            </button>
          );
        })}
      </div> : null}
      <div className="tr-catalog-products">
        {tab === "strategies" ? (
          strategies.length === 0 ? <p>{t("empty")}</p> : strategies.map((item, index) => {
            const ref = String(item.strategy_ref ?? item.id ?? index);
            return (
              <article key={ref}>
                <button type="button" className="tr-catalog-card-link" onClick={() => setStrategyDetail(ref)}>
                  <b>{String(item.name ?? item.title ?? ref)}</b>
                </button>
                <small>{String(item.description ?? "")}</small>
              </article>
            );
          })
        ) : tab === "factors" ? (
          factors.length === 0 ? <p>{t("empty")}</p> : factors.map((factor, index) => (
            <article key={String(factor.ref ?? factor.factor_ref ?? factor.alias ?? index)}>
              <b>{String(factor.name ?? factor.alias ?? factor.ref ?? "—")}</b>
              <small>{String(factor.family_ref ?? factor.family ?? "")}</small>
            </article>
          ))
        ) : loading ? <p>{t("loading")}</p> : products.length === 0 ? <p>{t("empty")}</p> : products.map((product, index) => (
          <article key={String(product.id ?? product.name ?? index)}>
            <b>{product.name ?? product.title ?? product.id}</b>
            <small>{product.data_source ?? ""}</small>
          </article>
        ))}
      </div>
      {tab === "strategies" && strategies.length < strategyTotal ? (
        <button type="button" className="tr-mobile-load-more" disabled={loading} onClick={() => setStrategyPage((value) => value + 1)}>{t("more")}</button>
      ) : null}
      {strategyDetail ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={t("catalog.strategies")}>
          <div className="tr-legacy-bar"><strong>{strategyDetail}</strong><button type="button" onClick={() => setStrategyDetail("")}>{t("notifications.close")}</button></div>
          {strategyData ? <pre className="tr-job-detail">{JSON.stringify(strategyData, null, 2)}</pre> : <p className="tr-catalog-detail-loading">{t("loading")}</p>}
        </div>
      ) : null}
      {legacy ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={t("catalog.legacy")}>
          <div className="tr-legacy-bar"><strong>{t("catalog.legacy")}</strong><button type="button" onClick={() => setLegacy(false)}>{t("notifications.close")}</button></div>
          <iframe title={t("catalog.legacy")} src="/products?presentation=embedded" />
        </div>
      ) : null}
    </section>
  );
}
