import { catalogRows, catalogSearchMatches } from "../catalog-search.ts";
import { sourceIdentity } from "../source-model.ts";
import React, { useEffect, useMemo, useState } from "react";
import { Button, Input, Select, Tabs, Tag } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { StrategyDetail } from "../components/strategy-detail.tsx";
import { FactorDetail } from "../components/factor-detail.tsx";
import { FunctionPage } from "../components/function-page.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { LibraryCreate } from "../components/library-create.tsx";
import { ProductGroupEditor } from "../components/product-group-editor.tsx";
import { ResultView } from "../components/result-view.tsx";
import { request } from "../configuration/api.ts";
import { formatDate } from "../format.ts";
import { usePageInstance } from "../page-instance.ts";
import { useCompactLayout } from "../configuration/layout.ts";

type Row = Record<string, any>;
type Domain = "products" | "factors" | "strategies";
const tabsByDomain = { products: ["products", "groups", "sources", "categories", "reference"], factors: ["factors", "families", "sets"], strategies: ["public", "mine", "subordinates", "shared", "strategyFamilies"] };
const identity = (row: Row): string => String(row.group_ref || row.ref || row.factor_ref || row.strategy_ref || row.template_ref || row.family_ref || row.set_ref || row.id || row.family_id || row.bundle_id || row.source_name || row.factor_family_alias || row.alias || row.name || "");
const title = (row: Row): string => String(row.family_name || row.bundle_name || row.source_name || row.name || row.title || row.factor_family_name || row.factor_alias || row.alias || identity(row));
const owner = (row: Row): string => String(row.owner_username || row.owner || row.owner_ref || "—");
const family = (row: Row): string => String(row.factor_family_alias || row.family_alias || row.identity?.family_alias || row.family_ref || "—");

export function CatalogPage({ domain = "products" }: { domain?: Domain }): React.ReactElement {
  const { t } = useTranslation(), mobile = useCompactLayout(), instance = usePageInstance();
  const [tab, setTab] = useState(tabsByDomain[domain][0]);
  const [rows, setRows] = useState<Row[]>([]), [total, setTotal] = useState(0);
  const [query, setQuery] = useState(""), [familyFilter, setFamilyFilter] = useState<string>(), [ownerFilter, setOwnerFilter] = useState<string>();
  const [page, setPage] = useState(1), [size, setSize] = useState(20), [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null), [detail, setDetail] = useState<Row | null>(null), [detailError, setDetailError] = useState("");
  const [creating, setCreating] = useState(false), [detailOpen, setDetailOpen] = useState(false);
  const [groupCreating, setGroupCreating] = useState(false), [groupEditing, setGroupEditing] = useState(false);
  const serverPaged = domain === "strategies" && !["public", "strategyFamilies"].includes(tab);
  useEffect(() => {
    if (tab === "reference") { setRows([]); return; }
    const controller = new AbortController(); setLoading(true); setError("");
    const url = domain === "strategies" ? ["public", "strategyFamilies"].includes(tab) ? "/api/strategy-library/factor-strategies" : `/api/strategy-library/strategies?scope=${tab}&page=${page}&limit=${size}&query=${encodeURIComponent(query)}`
      : tab === "products" ? "/api/product-library/products" : tab === "groups" ? "/api/product-library/product-groups?view=summary" : tab === "sources" ? "/api/product-library/data-sources" : tab === "categories" ? "/api/product-library/categories"
      : tab === "families" ? "/api/factor-library/families" : tab === "sets" ? "/api/factor-library/factor-sets" : "/api/factor-library/factors";
    const timer = setTimeout(() => {
      void request(url, { signal: controller.signal }).then((data) => {
        if (controller.signal.aborted) return;
        const items = catalogRows(data, domain, tab);
        setRows(items); setTotal(data.total ?? items.length);
      }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, serverPaged ? 200 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [domain, tab, serverPaged, serverPaged ? page : 0, serverPaged ? size : 0, serverPaged ? query : "", revision]);
  useEffect(() => {
    setDetail(null); setDetailError(""); setGroupEditing(false); if (!selected) return;
    const controller = new AbortController(), ref = encodeURIComponent(identity(selected));
    const url = tab === "factors" ? `/api/factor-library/factors/detail?factor_ref=${ref}${selected.owner_username ? `&owner_username=${encodeURIComponent(selected.owner_username)}` : ""}`
      : domain === "strategies" && !["public", "strategyFamilies"].includes(tab) ? `/api/strategy-library/strategies/${ref}?include_source=0`
      : tab === "groups" ? `/api/product-library/product-groups/${ref}` : null;
    if (!url) { setDetail(selected); return; }
    void request(url, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setDetail(data); }).catch((reason) => { if (!controller.signal.aborted) setDetailError(reason.message); });
    return () => controller.abort();
  }, [selected, tab, domain]);
  const displayTitle = (row: Row): string => row.template_ref ? t(`configuration.templates.${row.template_ref.split(":").pop()}`, { defaultValue: title(row) }) : title(row);
  const filtered = useMemo(() => rows.filter((row) => (serverPaged || catalogSearchMatches(query, [displayTitle(row), family(row), owner(row)], domain === "products" ? [row.desc, row.exchange] : [])) && (!familyFilter || family(row) === familyFilter) && (!ownerFilter || owner(row) === ownerFilter)), [rows, query, familyFilter, ownerFilter, serverPaged, t]);
  const visible = serverPaged ? filtered : filtered.slice((page - 1) * size, page * size);
  const label = (key: string): string => t(domain === "strategies" ? `library.scopes.${key}` : `catalog.${key}`);
  const select = (row: Row): void => { if (tab === "sources") { instance.open("source-detail", {sourceFamilyId: sourceIdentity(row)}); return; } if (tab === "products") { instance.open("product-detail", { productName: row.name || row.code || row.id, productTitle: row.desc || row.name || row.code }); return; } setSelected(row); if (mobile) setDetailOpen(true); };
  const groupDetail = (detail as Row | null)?.group ?? detail ?? selected;
  const contents = detailError ? <div role="alert">{detailError}</div> : tab === "groups" && groupEditing ? <ProductGroupEditor group={groupDetail as Row} onCancel={() => setGroupEditing(false)} onSaved={(value) => { setGroupEditing(false); setSelected(value); setDetail({ group: value } as Row); setRevision((revision) => revision + 1); }} /> : tab === "factors" || tab === "families" ? <FactorDetail key={identity(selected || {})} detail={detail} /> : domain === "strategies" && !["public", "strategyFamilies"].includes(tab) ? <StrategyDetail onRemoved={() => { setSelected(null); setDetailOpen(false); setRevision((value) => value + 1); }} key={identity(selected || {})} detail={detail} onUpdated={(value) => { setSelected(value); setRevision((revision) => revision + 1); }} /> : tab === "groups" ? <div className="tr-group-detail"><ResultView value={detail} /><Button onClick={() => setGroupEditing(true)}>{t("productGroup.edit")}</Button></div> : <ResultView value={detail} />;
  if (creating) return <FunctionPage title={t(domain === "factors" ? "editor.newFactor" : "editor.newStrategy")}><LibraryCreate kind={domain === "factors" ? "factor" : "strategy"} onCancel={() => setCreating(false)} onCreated={() => { setCreating(false); setRevision((value) => value + 1); }} /></FunctionPage>;
  if (groupCreating) return <FunctionPage title={t("productGroup.create")}><ProductGroupEditor onCancel={() => setGroupCreating(false)} onSaved={(value) => { setGroupCreating(false); setRevision((revision) => revision + 1); setSelected(value); }} /></FunctionPage>;
  return <FunctionPage title={t(`nav.${domain}`)} actions={<><Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision((value) => value + 1)} />{domain === "products" && tab === "groups" ? <Button type="primary" icon={<PlusOutlined />} onClick={() => setGroupCreating(true)}>{t("productGroup.create")}</Button> : null}{domain !== "products" ? <Button type="primary" aria-label={t(domain === "factors" ? "editor.newFactor" : "editor.newStrategy")} icon={<PlusOutlined />} onClick={() => setCreating(true)}>{t(domain === "factors" ? "editor.newFactor" : "editor.newStrategy")}</Button> : null}</>}>
    <Tabs activeKey={tab} onChange={(value) => { setTab(value); setPage(1); setRows([]); setSelected(null); setQuery(""); setOwnerFilter(undefined); setFamilyFilter(undefined); }} items={tabsByDomain[domain].map((key) => ({ key, label: label(key) }))} />
    {tab === "reference" ? <ReferenceLookup /> : <><div className="tr-library-filters"><Input.Search allowClear aria-label={t(domain === "products" && tab === "products" ? "market.productSearch" : "library.search")} placeholder={t(domain === "products" && tab === "products" ? "market.productSearch" : "library.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
      {domain === "factors" ? <Select allowClear aria-label={t("library.allFamilies")} placeholder={t("library.allFamilies")} value={familyFilter} options={[...new Set(rows.map(family))].filter((name) => name !== "—").map((name) => ({ value: name, label: name }))} onChange={(value) => { setFamilyFilter(value); setPage(1); }} /> : null}
      {!serverPaged && domain !== "products" ? <Select allowClear aria-label={t("library.allOwners")} placeholder={t("library.allOwners")} value={ownerFilter} options={[...new Set(rows.map(owner))].filter((name) => name !== "—").map((name) => ({ value: name, label: name }))} onChange={(value) => { setOwnerFilter(value); setPage(1); }} /> : null}
      <Button onClick={() => { setQuery(""); setFamilyFilter(undefined); setOwnerFilter(undefined); setPage(1); }}>{t("library.reset")}</Button></div>
    <TRDataTable rows={visible} rowKey={identity} rowSelection={{ type: "radio", selectedRowKeys: selected ? [identity(selected)] : [], onSelect: select }} loading={loading} error={error} pagination={{ page, pageSize: size, total: serverPaged ? total : filtered.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t(domain === "products" && tab === "products" ? "market.identifier" : "editor.name"), key: "name", render: (_: unknown, row: Row) => <button className={`tr-table-link ${selected && identity(row) === identity(selected) ? "is-selected" : ""}`} onClick={() => select(row)}>{displayTitle(row)}{mobile ? <small className="tr-library-row-meta">{domain === "products" ? [row.exchange, row.desc].filter(Boolean).join(" · ") : `${family(row)} · ${owner(row)}`}</small> : null}</button> },
      ...(domain === "factors" ? [{ title: t("catalog.families"), key: "family", responsive: ["md"] as "md"[], render: (_: unknown, row: Row) => family(row) }] : []),
      ...(domain === "products" ? [
        ...(tab === "sources" ? [
          { title: t("sources.provider"), dataIndex: "provider_kind" },
          { title: t("sources.frequencies"), key: "frequencies", render: (_: unknown, row: Row) => row.availability?.frequency_names?.join(" · ") || "—" },
          { title: t("sources.products"), key: "products", render: (_: unknown, row: Row) => row.availability?.product_count ?? "—" },
        ] : [{ title: t("market.exchange"), dataIndex: "exchange", responsive: ["md"] as "md"[] }]),
        ...(tab === "sources" ? [] : [{ title: t("market.description"), dataIndex: "desc", responsive: ["md"] as "md"[] }]),
      ] : [
      { title: t("library.version"), key: "version", responsive: ["md"] as "md"[], render: (_: unknown, row: Row) => <span className="tr-version-ref" title={row.current_revision?.revision_ref || row.revision_ref || row.ref}>{row.version || row.current_revision?.revision_ref || row.revision_ref || row.ref || "—"}</span> },
      { title: t("library.owner"), key: "owner", responsive: ["md"] as "md"[], render: (_: unknown, row: Row) => owner(row) },
      { title: t("jobs.updated"), dataIndex: "updated_at", responsive: ["lg"] as "lg"[], render: (value: string) => value ? formatDate(value, { dateStyle: "medium", timeStyle: "short" }) : "—" },
      ]),
    ]} />
    {selected && !mobile && !detailOpen ? <section className="tr-library-detail"><header><h2>{displayTitle(selected)}</h2><Button onClick={() => setDetailOpen(true)}>{t("details")}</Button></header><div className="tr-library-meta">{domain === "factors" && family(selected) !== "—" ? <span>{family(selected)}</span> : null}{owner(selected) !== "—" ? <span>{owner(selected)}</span> : null}{selected.version || selected.current_revision?.revision_number ? <Tag>{selected.version || `r${selected.current_revision.revision_number}`}</Tag> : null}</div>{contents}</section> : null}
    </>}
    {selected && detailOpen ? <DetailsPanel title={displayTitle(selected)} onClose={() => setDetailOpen(false)}>{contents}</DetailsPanel> : null}
  </FunctionPage>;
}

function ReferenceLookup(): React.ReactElement {
  const { t } = useTranslation(); const [kind, setKind] = useState("contract"), [ref, setRef] = useState(""), [lookup, setLookup] = useState("");
  const [value, setValue] = useState<unknown>(null);
  useEffect(() => { if (!lookup) { setValue(null); return; } const controller = new AbortController();
    void request(`/api/report-references/validate?kind=${encodeURIComponent(kind)}&target_ref=${encodeURIComponent(lookup)}`, { signal: controller.signal }).then(setValue).catch((reason) => { if (!controller.signal.aborted) setValue({ error: reason.message }); });
    return () => controller.abort();
  }, [lookup, kind]);
  return <><div className="tr-library-filters"><Select aria-label={t("catalog.reference")} value={kind} onChange={setKind} options={["contract", "continuous-contract", "factor", "strategy"].map((value) => ({ value, label: t(`library.references.${value}`) }))} /><Input.Search aria-label={t("catalog.referenceHint")} placeholder={t("catalog.referenceHint")} value={ref} onChange={(event) => setRef(event.target.value)} onSearch={setLookup} /></div><ResultView value={value} /></>;
}
