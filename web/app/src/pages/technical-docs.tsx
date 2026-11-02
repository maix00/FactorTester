import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Spin, Tabs } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { usePageInstance } from "../page-instance.ts";
import "../components/network-topology.css";

type DocPage = { slug: string; title: string; summary?: string; section_title?: string };
type DocIndex = { default_page?: string; sections?: { title: string; pages?: DocPage[] }[] };

const FEATURE_PAGES = ["network-topology", "identity-permissions", "backtest-trading", "factor-representation"];

function NetworkTopology(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const language = (i18n.resolvedLanguage || i18n.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en";
  return <section className="tr-topology" aria-label={t("technicalDocs.topologyLabel")}>
    <p className="tr-topology-hint"><span aria-hidden="true">↔ </span>{t("technicalDocs.scrollHint", { defaultValue: language === "zh" ? "左右滑动查看完整拓扑" : "Swipe horizontally to view the full diagram" })}</p>
    <div className="tr-topology-canvas" tabIndex={0}>
      <img className="tr-topology-image" src={`/research-static/vendor/web-app/network-topology.${language}.svg`}
        alt={`${t("technicalDocs.topologyTitle")} · ${t("technicalDocs.crossHostArrowFlightPlanned")} · ${t("technicalDocs.managerOnlyPath")}`} />
    </div>
  </section>;
}

export function TechnicalDocsPage(): React.ReactElement {
  const { t } = useTranslation();
  const instance = usePageInstance();
  const article = useRef<HTMLElement>(null);
  const initialDoc = useRef(FEATURE_PAGES[0]);
  const [index, setIndex] = useState<DocIndex | null>(null);
  const [slug, setSlug] = useState(FEATURE_PAGES[0]);
  const [html, setHTML] = useState("");
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const pages = useMemo(() => (index?.sections || []).flatMap(section => (section.pages || []).map(page => ({ ...page, section_title: section.title }))), [index]);
  const featured = FEATURE_PAGES.flatMap(key => {
    const page = pages.find(item => item.slug === key);
    return page ? [page] : [];
  });
  const filtered = pages.filter(page => `${page.title} ${page.summary || ""} ${page.section_title || ""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));

  useEffect(() => {
    if (!instance.mobile) return;
    const update = (event: PopStateEvent): void => {
      if (event.state?.trPage === instance.id) {
        const previous = event.state?.trDoc;
        setSlug(typeof previous === "string" && previous ? previous : initialDoc.current);
      }
    };
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, [instance.id, instance.mobile]);
  const openDoc = (next: string): void => {
    if (next === slug) return;
    if (instance.mobile) history.pushState({ ...history.state, trPage: instance.id, trDoc: next }, "", location.href);
    setSlug(next);
  };

  useEffect(() => {
    const controller = new AbortController(); setError("");
    void request("/api/docs/index", { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) {
        setIndex(value);
        if (!(value.sections || []).some((section: { pages?: DocPage[] }) => (section.pages || []).some(page => page.slug === slug))) {
          initialDoc.current = value.default_page || "getting-started";
          setSlug(initialDoc.current);
        }
      }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (!slug) return;
    const controller = new AbortController(); setLoading(true); setError(""); setHTML("");
    void request(`/api/docs/pages/${encodeURIComponent(slug)}`, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) { setHTML(value.html || ""); setTitle(value.title || slug); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [slug, revision]);

  return <FunctionPage title={t("nav.technical-docs")} actions={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRevision(value => value + 1)}>{t("configuration.reload")}</Button>}>
    <div className="tr-technical-docs-toolbar">
      <Input.Search allowClear aria-label={t("technicalDocs.search")} placeholder={t("technicalDocs.search")} value={query} onChange={event => setQuery(event.target.value)} />
    </div>
    {loading && !index ? <Spin /> : error && !index ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : <>
      {featured.length > 0 && <Tabs activeKey={slug} onChange={openDoc} items={featured.map(page => ({ key: page.slug, label: page.title }))} />}
      {query && !filtered.some(page => page.slug === slug) && <div className="tr-technical-docs-search-results">{filtered.map(page => <Button key={page.slug} type="link" onClick={() => openDoc(page.slug)}>{page.title}</Button>)}</div>}
      {error ? <Alert type="error" showIcon message={error} /> : loading ? <Spin /> : !html ? <Empty description={t("empty")} /> : <>
        {slug === "network-topology" ? <NetworkTopology /> : null}
        <article ref={article} className="tr-technical-document" onClick={event => {
          const link = (event.target as HTMLElement).closest("a"); if (!link) return;
          const href = link.getAttribute("href") || "";
          if (href.startsWith("/docs/")) { event.preventDefault(); const target = decodeURIComponent(href.split("#")[0].slice(6) || slug); openDoc(target); }
        }}><h2>{title}</h2><div dangerouslySetInnerHTML={{ __html: html }} /></article>
      </>}
    </>}
  </FunctionPage>;
}
