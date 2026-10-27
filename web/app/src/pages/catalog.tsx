import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DetailsPanel } from "../components/details-panel.tsx";
import { ResultView } from "../components/result-view.tsx";
import { Button } from "antd";
import { LibraryCreate } from "../components/library-create.tsx";
import { notify } from "../notifications/core.ts";

type Group = { id?: string; name?: string; title?: string; description?: string; member_count?: number; product_count?: number };
type Product = { id?: string; name?: string; title?: string; data_source?: string };
type Payload<T> = { groups?: T[]; products?: T[]; sources?: { id: string; name?: string }[] };

export function CatalogPage({ domain = "products" }: { domain?: "products" | "factors" | "strategies" }): React.ReactElement {
  const { t } = useTranslation();
  const [creating, setCreating] = useState(false);
  const [groups, setGroups] = useState<Group[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"products" | "factors" | "families" | "sets" | "strategies" | "sources" | "categories" | "reference">(domain);
  const [sources, setSources] = useState<{ id: string; name?: string; visitor_data_accessible?: boolean }[]>([]);
  const [categories, setCategories] = useState<{ id?: string; name?: string; title?: string }[]>([]);
  const [families, setFamilies] = useState<Record<string, unknown>[]>([]);
  const [sets, setSets] = useState<Record<string, unknown>[]>([]);
  const [strategies, setStrategies] = useState<Record<string, unknown>[]>([]);
  const [strategyPage, setStrategyPage] = useState(1);
  const [strategyTotal, setStrategyTotal] = useState(0);
  const [strategyDetail, setStrategyDetail] = useState<string>("");
  const [strategyData, setStrategyData] = useState<Record<string, unknown> | null>(null);
  const [factorDetail, setFactorDetail] = useState<string>("");
  const [factorData, setFactorData] = useState<Record<string, unknown> | null>(null);
  const [groupDetail, setGroupDetail] = useState<string>("");
  const [groupData, setGroupData] = useState<Record<string, unknown> | null>(null);
  const [productSelected, setProductSelected] = useState<Record<string, unknown> | null>(null);
  const [sourceSelected, setSourceSelected] = useState<Record<string, unknown> | null>(null);
  const [categorySelected, setCategorySelected] = useState<Record<string, unknown> | null>(null);
  const [referenceKind, setReferenceKind] = useState("contract");
  const [referenceRef, setReferenceRef] = useState("");
  const [referenceData, setReferenceData] = useState<Record<string, unknown> | null>(null);
  const [familySelected, setFamilySelected] = useState<Record<string, unknown> | null>(null);
  const [factorSetSelected, setFactorSetSelected] = useState<Record<string, unknown> | null>(null);
  const [factors, setFactors] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    fetch("/api/product-library/product-groups?view=summary", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: Payload<Group>) => setGroups(payload.groups ?? []))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [t]);

  useEffect(() => {
    if (tab !== "reference" || !referenceRef) { setReferenceData(null); return; }
    setLoading(true);
    fetch(`/api/report-references/validate?kind=${encodeURIComponent(referenceKind)}&target_ref=${encodeURIComponent(referenceRef)}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setReferenceData(value))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [tab, referenceKind, referenceRef, t]);

  useEffect(() => {
    if (tab !== "families" && tab !== "sets") return;
    setLoading(true);
    const path = tab === "families" ? "/api/factor-library/families" : "/api/factor-library/factor-sets";
    fetch(path, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { families?: Record<string, unknown>[]; items?: Record<string, unknown>[] }) => {
        if (tab === "families") setFamilies(payload.families ?? []); else setSets(payload.items ?? []);
      })
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [tab, t]);

  useEffect(() => {
    if (tab !== "sources" && tab !== "categories") return;
    setLoading(true);
    const path = tab === "sources" ? "/api/product-library/data-sources" : "/api/product-library/categories";
    fetch(path, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { sources?: typeof sources; categories?: typeof categories }) => {
        if (tab === "sources") setSources(payload.sources ?? []); else setCategories(payload.categories ?? []);
      })
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [tab, t]);

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
    if (!groupDetail) { setGroupData(null); return; }
    setGroupData(null);
    fetch(`/api/product-library/product-groups/${encodeURIComponent(groupDetail)}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setGroupData(value))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [groupDetail, t]);

  useEffect(() => {
    if (!factorDetail) { setFactorData(null); return; }
    setFactorData(null);
    fetch(`/api/factor-library/factors/detail?factor_ref=${encodeURIComponent(factorDetail)}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setFactorData(value))
      .catch((error: Error) => notify({ code: "catalog.load", type: "error", message: t("loadFailed"), description: error.message }));
  }, [factorDetail, t]);

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

  if (creating && domain !== "products") return <section className="tr-function-page"><div className="tr-function-body"><LibraryCreate kind={domain === "factors" ? "factor" : "strategy"} onCancel={() => setCreating(false)} onCreated={() => { setCreating(false); if (domain === "strategies") setStrategyPage(1); }} /></div></section>;

  return (
    <section className="tr-catalog-page">
      <header>
        <div><h1>{t(`nav.${domain}`)}</h1></div>
        {domain !== "products" ? <Button type="primary" onClick={() => setCreating(true)}>{t(domain === "factors" ? "editor.newFactor" : "editor.newStrategy")}</Button> : null}
      </header>
      <div className="tr-catalog-tabs">
        {["products", "sources", "categories", "reference"].includes("products") && domain === "products" ? <button type="button" className={tab === "products" ? "is-active" : ""} onClick={() => setTab("products")}>{t("catalog.products")}</button> : null}
        {["factors", "families", "sets"].includes("factors") && domain === "factors" ? <button type="button" className={tab === "factors" ? "is-active" : ""} onClick={() => setTab("factors")}>{t("catalog.factors")}</button> : null}
        {["strategies"].includes("strategies") && domain === "strategies" ? <button type="button" className={tab === "strategies" ? "is-active" : ""} onClick={() => { setTab("strategies"); setStrategyPage(1); }}>{t("catalog.strategies")}</button> : null}
        {["factors", "families", "sets"].includes("families") && domain === "factors" ? <button type="button" className={tab === "families" ? "is-active" : ""} onClick={() => setTab("families")}>{t("catalog.families")}</button> : null}
        {["factors", "families", "sets"].includes("sets") && domain === "factors" ? <button type="button" className={tab === "sets" ? "is-active" : ""} onClick={() => setTab("sets")}>{t("catalog.sets")}</button> : null}
        {["products", "sources", "categories", "reference"].includes("sources") && domain === "products" ? <button type="button" className={tab === "sources" ? "is-active" : ""} onClick={() => setTab("sources")}>{t("catalog.sources")}</button> : null}
        {["products", "sources", "categories", "reference"].includes("categories") && domain === "products" ? <button type="button" className={tab === "categories" ? "is-active" : ""} onClick={() => setTab("categories")}>{t("catalog.categories")}</button> : null}
        {["products", "sources", "categories", "reference"].includes("reference") && domain === "products" ? <button type="button" className={tab === "reference" ? "is-active" : ""} onClick={() => setTab("reference")}>{t("catalog.reference")}</button> : null}
      </div>
      {tab === "products" ? <div className="tr-catalog-groups">
        <button type="button" className={selected ? "" : "is-active"} onClick={() => setSelected("")}>{t("catalog.all")}</button>
        {groups.map((group) => {
          const id = String(group.id ?? group.name ?? "");
          return (
            <div key={id} className={`tr-catalog-group${selected === id ? " is-active" : ""}`}>
              <button type="button" onClick={() => setSelected(id)}>
                <b>{group.name ?? group.title ?? id}</b>
                <small>{group.member_count ?? group.product_count ?? 0} {t("catalog.members")}</small>
              </button>
              <button type="button" className="tr-catalog-group-detail" onClick={() => setGroupDetail(id)}>{t("jobs.detail")}</button>
            </div>
          );
        })}
      </div> : null}
      <div className="tr-catalog-products">
        {tab === "reference" ? (
          <div className="tr-catalog-reference">
            <select value={referenceKind} onChange={(event) => setReferenceKind(event.target.value)}>
              <option value="contract">contract</option>
              <option value="continuous-contract">continuous-contract</option>
              <option value="factor">factor</option>
              <option value="strategy">strategy</option>
            </select>
            <input value={referenceRef} onChange={(event) => setReferenceRef(event.target.value)} placeholder={t("catalog.referenceHint")} />
            {referenceData ? <pre className="tr-job-detail">{JSON.stringify(referenceData, null, 2)}</pre> : loading ? <p>{t("loading")}</p> : null}
          </div>
        ) : tab === "families" ? (
          families.length === 0 ? <p>{t("empty")}</p> : families.map((item, index) => (
            <article key={String(item.family_ref ?? item.id ?? index)}>
              <button type="button" className="tr-catalog-card-link" onClick={() => setFamilySelected(item)}><b>{String(item.name ?? item.title ?? item.family_ref ?? "—")}</b></button>
              <small>{String(item.description ?? "")}</small>
            </article>
          ))
        ) : tab === "sets" ? (
          sets.length === 0 ? <p>{t("empty")}</p> : sets.map((item, index) => (
            <article key={String(item.set_ref ?? item.id ?? index)}>
              <button type="button" className="tr-catalog-card-link" onClick={() => setFactorSetSelected(item)}><b>{String(item.name ?? item.title ?? item.set_ref ?? "—")}</b></button>
              <small>{String(item.description ?? "")}</small>
            </article>
          ))
        ) : tab === "sources" ? (
          sources.length === 0 ? <p>{t("empty")}</p> : sources.map((source) => (
            <article key={source.id}>
              <button type="button" className="tr-catalog-card-link" onClick={() => setSourceSelected(source as unknown as Record<string, unknown>)}><b>{source.name ?? source.id}</b></button>
              <small>{source.id}</small>
            </article>
          ))
        ) : tab === "categories" ? (
          categories.length === 0 ? <p>{t("empty")}</p> : categories.map((category, index) => (
            <article key={String(category.id ?? index)}>
              <button type="button" className="tr-catalog-card-link" onClick={() => setCategorySelected(category as unknown as Record<string, unknown>)}><b>{category.name ?? category.title ?? category.id ?? "—"}</b></button>
            </article>
          ))
        ) : tab === "strategies" ? (
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
              <button type="button" className="tr-catalog-card-link" onClick={() => setFactorDetail(String(factor.ref ?? factor.factor_ref ?? factor.alias ?? ""))}>
                <b>{String(factor.name ?? factor.alias ?? factor.ref ?? "—")}</b>
              </button>
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
      {familySelected ? <DetailsPanel title={String(familySelected.name || familySelected.family_ref || t("catalog.families"))} onClose={() => setFamilySelected(null)}><ResultView value={familySelected} /></DetailsPanel> : null}
      {factorSetSelected ? <DetailsPanel title={t("catalog.sets")} onClose={() => setFactorSetSelected(null)}><ResultView value={factorSetSelected} /></DetailsPanel> : null}
      {sourceSelected ? <DetailsPanel title={String(sourceSelected.name || sourceSelected.id)} onClose={() => setSourceSelected(null)}><ResultView value={sourceSelected} /></DetailsPanel> : null}
      {categorySelected ? <DetailsPanel title={t("catalog.categories")} onClose={() => setCategorySelected(null)}><ResultView value={categorySelected} /></DetailsPanel> : null}
      {productSelected ? <DetailsPanel title={String(productSelected.name || productSelected.id)} onClose={() => setProductSelected(null)}><ResultView value={productSelected} /></DetailsPanel> : null}
      {groupDetail ? <DetailsPanel title={groupDetail} onClose={() => setGroupDetail("")}><ResultView value={groupData} /></DetailsPanel> : null}
      {factorDetail ? <DetailsPanel title={t("catalog.factors")} onClose={() => setFactorDetail("")}><ResultView value={factorData} /></DetailsPanel> : null}
      {strategyDetail ? <DetailsPanel title={t("catalog.strategies")} onClose={() => setStrategyDetail("")}><ResultView value={strategyData} /></DetailsPanel> : null}
    </section>
  );
}
