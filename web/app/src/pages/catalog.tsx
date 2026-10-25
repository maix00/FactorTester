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

  useEffect(() => {
    fetch("/api/product-library/product-groups?view=summary", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: Payload<Group>) => setGroups(payload.groups ?? []))
      .catch((error: Error) => notify({ code: "catalog.groups", type: "error", message: t("loadFailed"), description: error.message }));
  }, [t]);

  useEffect(() => {
    setLoading(true);
    const query = selected ? `?group_ref=${encodeURIComponent(selected)}` : "";
    fetch(`/api/product-library/products${query}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: Payload<Product>) => setProducts(payload.products ?? []))
      .catch((error: Error) => notify({ code: "catalog.products", type: "error", message: t("loadFailed"), description: error.message }))
      .finally(() => setLoading(false));
  }, [selected, t]);

  return (
    <section className="tr-catalog-page">
      <header>
        <div><h1>{t("nav.catalog")}</h1><p>{t("catalog.hint")}</p></div>
        <button type="button" className="tr-toolbar-button" onClick={() => setLegacy(true)}>{t("catalog.legacy")}</button>
      </header>
      <div className="tr-catalog-groups">
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
      </div>
      <div className="tr-catalog-products">
        {loading ? <p>{t("loading")}</p> : products.length === 0 ? <p>{t("empty")}</p> : products.map((product, index) => (
          <article key={String(product.id ?? product.name ?? index)}>
            <b>{product.name ?? product.title ?? product.id}</b>
            <small>{product.data_source ?? ""}</small>
          </article>
        ))}
      </div>
      {legacy ? (
        <div className="tr-legacy-overlay" role="dialog" aria-label={t("catalog.legacy")}>
          <div className="tr-legacy-bar"><strong>{t("catalog.legacy")}</strong><button type="button" onClick={() => setLegacy(false)}>{t("notifications.close")}</button></div>
          <iframe title={t("catalog.legacy")} src="/products?presentation=embedded" />
        </div>
      ) : null}
    </section>
  );
}
