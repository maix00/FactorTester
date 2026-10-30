import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Spin, Tabs } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { FunctionPage } from "../components/function-page.tsx";

type DocPage = { slug: string; title: string; summary?: string; section_title?: string };
type DocIndex = { default_page?: string; sections?: { title: string; pages?: DocPage[] }[] };

const FEATURE_PAGES = ["network-topology", "identity-permissions", "backtest-trading", "factor-representation"];

function NetworkTopology(): React.ReactElement {
  const { t } = useTranslation();
  return <section className="tr-topology" aria-label={t("technicalDocs.topologyLabel")}>
    <div className="tr-topology-canvas">
      <svg viewBox="0 0 1080 930" role="img" aria-labelledby="tr-topology-title tr-topology-desc">
        <title id="tr-topology-title">{t("technicalDocs.topologyTitle")}</title>
        <desc id="tr-topology-desc">{t("technicalDocs.topologyDescription")}</desc>
        <defs>
          <marker id="tr-topology-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker>
          <marker id="tr-topology-arrow-planned" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker>
        </defs>
        <rect className="tr-topology-host" x="28" y="34" width="482" height="560" rx="14" />
        <text className="tr-topology-host-title" x="52" y="70">{t("technicalDocs.managerHost")}</text>
        <rect className="tr-topology-container" x="56" y="96" width="198" height="126" rx="10" />
        <text className="tr-topology-node-title" x="74" y="124">Manager</text>
        <text className="tr-topology-node-copy" x="74" y="151">{t("technicalDocs.managerResponsibilities")}</text>
        <text className="tr-topology-node-copy" x="74" y="174">OIDC · Job · API</text>
        <rect className="tr-topology-container" x="278" y="96" width="198" height="126" rx="10" />
        <text className="tr-topology-node-title" x="296" y="124">Keycloak</text>
        <text className="tr-topology-node-copy" x="296" y="151">{t("technicalDocs.identityStore")}</text>
        <text className="tr-topology-node-copy" x="296" y="174">Realm Groups · FGAP</text>
        <line className="tr-topology-link" x1="254" y1="154" x2="275" y2="154" markerEnd="url(#tr-topology-arrow)" />
        <rect className="tr-topology-container" x="56" y="254" width="420" height="102" rx="10" />
        <text className="tr-topology-node-title" x="74" y="283">PostgreSQL / CouchDB</text>
        <text className="tr-topology-node-copy" x="74" y="310">{t("technicalDocs.managerDatabase")}</text>
        <text className="tr-topology-node-copy" x="74" y="333">{t("technicalDocs.managerDatabaseDetail")}</text>
        <line className="tr-topology-link" x1="154" y1="222" x2="154" y2="250" markerEnd="url(#tr-topology-arrow)" />
        <rect className="tr-topology-container tr-topology-compute" x="56" y="390" width="198" height="154" rx="10" />
        <text className="tr-topology-node-title" x="74" y="420">Nautilus worker</text>
        <text className="tr-topology-node-copy" x="74" y="448">Celery · RunSpec</text>
        <text className="tr-topology-node-copy" x="74" y="471">{t("technicalDocs.computeNode")}</text>
        <text className="tr-topology-node-copy" x="74" y="514">{t("technicalDocs.optional")}</text>
        <rect className="tr-topology-container tr-topology-data" x="278" y="390" width="198" height="154" rx="10" />
        <text className="tr-topology-node-title" x="296" y="420">Data I/O</text>
        <text className="tr-topology-node-copy" x="296" y="448">Arrow IPC · mmap</text>
        <text className="tr-topology-node-copy" x="296" y="471">{t("technicalDocs.hostLocalCache")}</text>
        <text className="tr-topology-node-copy" x="296" y="514">{t("technicalDocs.optional")}</text>
        <line className="tr-topology-link" x1="254" y1="468" x2="275" y2="468" markerEnd="url(#tr-topology-arrow)" />

        <rect className="tr-topology-host tr-topology-internal" x="572" y="34" width="480" height="560" rx="14" />
        <text className="tr-topology-host-title" x="596" y="70">{t("technicalDocs.orgHost")}</text>
        <rect className="tr-topology-container" x="600" y="96" width="198" height="126" rx="10" />
        <text className="tr-topology-node-title" x="618" y="124">Manager</text>
        <text className="tr-topology-node-copy" x="618" y="151">{t("technicalDocs.orgAdmin")}</text>
        <text className="tr-topology-node-copy" x="618" y="174">{t("technicalDocs.localLogin")}</text>
        <rect className="tr-topology-container" x="822" y="96" width="198" height="126" rx="10" />
        <text className="tr-topology-node-title" x="840" y="124">Keycloak</text>
        <text className="tr-topology-node-copy" x="840" y="151">{t("technicalDocs.localRealm")}</text>
        <text className="tr-topology-node-copy" x="840" y="174">{t("technicalDocs.localGroups")}</text>
        <line className="tr-topology-link" x1="798" y1="154" x2="819" y2="154" markerEnd="url(#tr-topology-arrow)" />
        <rect className="tr-topology-container" x="600" y="254" width="420" height="102" rx="10" />
        <text className="tr-topology-node-title" x="618" y="283">{t("technicalDocs.orgDatabase")}</text>
        <text className="tr-topology-node-copy" x="618" y="310">{t("technicalDocs.orgDatabaseDetail")}</text>
        <text className="tr-topology-node-copy" x="618" y="333">{t("technicalDocs.localData")}</text>
        <line className="tr-topology-link" x1="700" y1="222" x2="700" y2="250" markerEnd="url(#tr-topology-arrow)" />
        <rect className="tr-topology-container tr-topology-compute" x="600" y="390" width="198" height="154" rx="10" />
        <text className="tr-topology-node-title" x="618" y="420">Nautilus worker</text>
        <text className="tr-topology-node-copy" x="618" y="448">{t("technicalDocs.remoteWorker")}</text>
        <text className="tr-topology-node-copy" x="618" y="471">{t("technicalDocs.sameHost")}</text>
        <text className="tr-topology-node-copy" x="618" y="514">{t("technicalDocs.optional")}</text>
        <rect className="tr-topology-container tr-topology-data" x="822" y="390" width="198" height="154" rx="10" />
        <text className="tr-topology-node-title" x="840" y="420">Data I/O</text>
        <text className="tr-topology-node-copy" x="840" y="448">{t("technicalDocs.arrowCache")}</text>
        <text className="tr-topology-node-copy" x="840" y="471">{t("technicalDocs.bundleSource")}</text>
        <text className="tr-topology-node-copy" x="840" y="514">{t("technicalDocs.optional")}</text>
        <line className="tr-topology-link" x1="798" y1="468" x2="819" y2="468" markerEnd="url(#tr-topology-arrow)" />

        <path className="tr-topology-link tr-topology-federation" d="M 255 120 C 365 20, 500 20, 600 120" markerEnd="url(#tr-topology-arrow)" />
        <text className="tr-topology-link-label" x="357" y="45">{t("technicalDocs.identityFederation")}</text>
        <path className="tr-topology-link tr-topology-transfer" d="M 255 196 C 365 286, 500 286, 600 196" markerEnd="url(#tr-topology-arrow)" />
        <text className="tr-topology-link-label" x="342" y="268">{t("technicalDocs.jobTransfer")}</text>
        <path className="tr-topology-link tr-topology-planned" d="M 820 487 C 735 610, 360 610, 255 487" markerEnd="url(#tr-topology-arrow-planned)" />
        <text className="tr-topology-link-label" x="394" y="585">{t("technicalDocs.crossHostArrowFlightPlanned")}</text>

        <rect className="tr-topology-host tr-topology-personal" x="28" y="632" width="482" height="260" rx="14" />
        <text className="tr-topology-host-title" x="52" y="670">{t("technicalDocs.desktopHost")}</text>
        <rect className="tr-topology-container" x="56" y="694" width="198" height="154" rx="10" />
        <text className="tr-topology-node-title" x="74" y="724">{t("technicalDocs.desktopApp")}</text>
        <text className="tr-topology-node-copy" x="74" y="752">{t("technicalDocs.clients")}</text>
        <text className="tr-topology-node-copy" x="74" y="782">{t("technicalDocs.desktopClient")}</text>
        <rect className="tr-topology-container tr-topology-compute" x="278" y="694" width="198" height="154" rx="10" />
        <text className="tr-topology-node-title" x="296" y="724">{t("technicalDocs.localRuntime")}</text>
        <text className="tr-topology-node-copy" x="296" y="752">{t("technicalDocs.localBundle")}</text>
        <text className="tr-topology-node-copy" x="296" y="782">{t("technicalDocs.notManagerCallable")}</text>

        <rect className="tr-topology-host tr-topology-data-only" x="572" y="632" width="480" height="260" rx="14" />
        <text className="tr-topology-host-title" x="596" y="670">{t("technicalDocs.dataOnlyHost")}</text>
        <rect className="tr-topology-container" x="600" y="694" width="420" height="102" rx="10" />
        <text className="tr-topology-node-title" x="618" y="724">{t("technicalDocs.dataOnlyBundle")}</text>
        <text className="tr-topology-node-copy" x="618" y="752">{t("technicalDocs.dataOnlyService")}</text>
        <text className="tr-topology-node-copy" x="618" y="779">{t("technicalDocs.noWorker")}</text>
        <text className="tr-topology-link-label" x="618" y="835">{t("technicalDocs.crossHostDataPlanned")}</text>
      </svg>
    </div>
    <div className="tr-topology-legend" aria-label={t("technicalDocs.legend")}>
      <span><i className="is-solid" />{t("technicalDocs.legendImplemented")}</span>
      <span><i className="is-dashed" />{t("technicalDocs.legendPlanned")}</span>
      <span><i className="is-node" />{t("technicalDocs.legendOptional")}</span>
    </div>
    <p className="tr-topology-boundary">{t("technicalDocs.managerOnlyPath")}</p>
  </section>;
}

export function TechnicalDocsPage(): React.ReactElement {
  const { t } = useTranslation();
  const article = useRef<HTMLElement>(null);
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
    const controller = new AbortController(); setError("");
    void request("/api/docs/index", { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) {
        setIndex(value);
        if (!(value.sections || []).some((section: { pages?: DocPage[] }) => (section.pages || []).some(page => page.slug === slug))) setSlug(value.default_page || "getting-started");
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

  return <FunctionPage title={t("nav.technicalDocs")} actions={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRevision(value => value + 1)}>{t("configuration.reload")}</Button>}>
    <div className="tr-technical-docs-toolbar">
      <Input.Search allowClear aria-label={t("technicalDocs.search")} placeholder={t("technicalDocs.search")} value={query} onChange={event => setQuery(event.target.value)} />
    </div>
    {loading && !index ? <Spin /> : error && !index ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : <>
      {featured.length > 0 && <Tabs activeKey={slug} onChange={setSlug} items={featured.map(page => ({ key: page.slug, label: page.title }))} />}
      {query && !filtered.some(page => page.slug === slug) && <div className="tr-technical-docs-search-results">{filtered.map(page => <Button key={page.slug} type="link" onClick={() => setSlug(page.slug)}>{page.title}</Button>)}</div>}
      {error ? <Alert type="error" showIcon message={error} /> : loading ? <Spin /> : !html ? <Empty description={t("empty")} /> : <>
        {slug === "network-topology" ? <NetworkTopology /> : null}
        <article ref={article} className="tr-technical-document" onClick={event => {
          const link = (event.target as HTMLElement).closest("a"); if (!link) return;
          const href = link.getAttribute("href") || "";
          if (href.startsWith("/docs/") || href.startsWith("#")) { event.preventDefault(); const target = decodeURIComponent(href.split("#")[0].slice(6) || slug); if (target !== slug) setSlug(target); }
        }}><h2>{title}</h2><div dangerouslySetInnerHTML={{ __html: html }} /></article>
      </>}
    </>}
  </FunctionPage>;
}
