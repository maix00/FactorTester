import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Collapse, Empty, Select, Spin, Tag, Tooltip } from "antd";
import { FullscreenOutlined, InfoCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { ResultView } from "../components/result-view.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { MarketChart } from "../components/market-chart.tsx";
import { loadChartRuntime, type MarketBar } from "../charts/runtime.ts";
import { DEFAULT_MARKET_SETTINGS, marketZone, priceRequest, termBands, type MarketSettings } from "../charts/market-model.ts";
import { request } from "../configuration/api.ts";
import { usePageInstance } from "../page-instance.ts";
import { notify } from "../notifications/core.ts";
import { productFieldRows } from "../product-fields.ts";
type Row = Record<string, any>;
const intervals = ["SOURCE", "MIN5", "MIN15", "MIN30", "HOUR1", "DAY1", "WEEK1"];
export function ProductDetailPage(): React.ReactElement {
  const { t } = useTranslation(), instance = usePageInstance();
  const product = instance.args.productName || "", contract = instance.args.contractUid;
  const [nodeInputs, setNodeInputs] = useState<{value:string;label:string;binding:{route_id:string;source_ref:string;product_ref:string}}[]>([]);
  useEffect(() => { const controller = new AbortController();
    request("/api/test-authoring/execution-targets",{signal:controller.signal}).then(value => {if (!controller.signal.aborted) setNodeInputs((value.targets || []).flatMap((row: any) => row.online && row.market_read_available ? row.offers.filter((offer:any) => offer.available && offer.product_ref === (contract || product)).map((offer:any) => ({value:JSON.stringify([row.route_id,offer.source_ref]),label:`${row.target.manager_id} → ${row.target.node_id} · ${offer.installation.bundle_id} · ${offer.bar_spec}`,binding:{route_id:row.route_id,source_ref:offer.source_ref,product_ref:offer.product_ref}})) : []));}).catch(() => {if (!controller.signal.aborted) setNodeInputs([]);});
    return () => controller.abort();
  },[product,contract]);
  const [applied, setApplied] = useState<MarketSettings>({ ...DEFAULT_MARKET_SETTINGS }), [draft, setDraft] = useState<MarketSettings>({ ...DEFAULT_MARKET_SETTINGS });
  const [payload, setPayload] = useState<Row | null>(null), [bars, setBars] = useState<MarketBar[]>([]), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false), [infoOpen, setInfoOpen] = useState(false), [settingsError, setSettingsError] = useState("");
  const [contracts, setContracts] = useState<Row[]>([]), [termAvailable, setTermAvailable] = useState(false), [termError, setTermError] = useState("");
  const [fields, setFields] = useState<unknown>(null), [fieldsError, setFieldsError] = useState("");
  const [page, setPage] = useState(1), [size, setSize] = useState(15), [selectedBand, setSelectedBand] = useState("");
  const chartCard = useRef<HTMLElement>(null), inFlight = useRef<AbortController | null>(null);
  const load = useCallback(async (selection: MarketSettings, fromSettings = false): Promise<void> => {
    if (!product) return;
    inFlight.current?.abort(); const controller = new AbortController(); inFlight.current = controller;
    setLoading(true); setSettingsError(""); setError("");
    try {
      const body = priceRequest(product, contract, selection);
      const data = await request("/api/market-data/prices", { method: "POST", body: JSON.stringify(body), signal: controller.signal });
      await loadChartRuntime(); if (controller.signal.aborted) return;
      const nextBars = window.FTPriceChart!.barsOf(data);
      setPayload(data); setBars(nextBars); setApplied(selection); setDraft(selection);
      if (fromSettings) setSettingsOpen(false);
    } catch (reason) {
      if (controller.signal.aborted) return;
      const message = (reason as Error).message;
      if (fromSettings) setSettingsError(message); else setError(message);
      notify({ type: "error", code: `market.load:${instance.id}`, message: t("market.loadFailed"), description: message });
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }, [product, contract, instance.id, t]);
  useEffect(() => { void load({ ...DEFAULT_MARKET_SETTINGS }); return () => inFlight.current?.abort(); }, [product, contract]);
  useEffect(() => {
    if (!product) return;
    const controller = new AbortController();
    setFields(null); setFieldsError("");
    void request(`/api/product-library/product-fields?name=${encodeURIComponent(contract || product)}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setFields(data.fields || data); }).catch((reason) => { if (!controller.signal.aborted) setFieldsError(reason.message); });
    if (!contract) void request(`/api/product-library/contracts?product=${encodeURIComponent(product)}`, { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) { setContracts(data.contracts || []); setTermAvailable(!!data.supports_term_structure); } }).catch((reason) => { if (!controller.signal.aborted) setTermError(reason.message); });
    return () => controller.abort();
  }, [product, contract]);
  const bands = useMemo(() => termBands(contracts), [contracts]);
  const onUnavailable = useCallback(() => notify({ type: "warning", code: `market.range:${instance.id}`, message: t("market.outsideRange") }), [instance.id, t]);
  const sources: Row[] = (payload?.available_sources || []).map((item: string | Row) => typeof item === "string" ? { alias: item } : item);
  const currentSource = sources.find((item) => item.alias === (draft.source || payload?.data_source));
  const live = currentSource?.delivery_mode === "live_stream";
  const zone = marketZone(applied, payload?.timezone);
  const metadata = payload ? Object.fromEntries(Object.entries(payload).filter(([key]) => !["data", "rows", "fields"].includes(key))) : null;
  const openSettings = (): void => { setDraft({ ...applied }); setSettingsError(""); setSettingsOpen(true); };
  const saveSettings = (): void => {
    if (draft.interval === "LIVE" && !live) { setSettingsError(t("market.liveUnavailable")); return; }
    try { priceRequest(product, contract, draft); } catch { setSettingsError(t("market.invalidRange")); return; }
    if (payload && JSON.stringify(priceRequest(product, contract, draft)) === JSON.stringify(priceRequest(product, contract, applied))) { setApplied(draft); setSettingsOpen(false); return; }
    void load({ ...draft }, true);
  };
  if (!product) return <FunctionPage title={t("nav.products")}><Empty description={t("empty")} /></FunctionPage>;
  return <FunctionPage title={instance.args.productTitle || contract || product}>
    <div className="tr-product-identity"><span>{product}</span>{contract ? <Tag>{t("market.instrument")}</Tag> : null}</div>
    <section className="tr-market-card" ref={chartCard}>
      <header className="tr-market-toolbar"><div className="tr-market-heading"><h2>{t("market.title")}</h2><span>{zone}</span>{payload ? <Tag>{payload.data_source} · {payload.freq}</Tag> : null}</div>
        <div className="tr-market-actions"><Tooltip title={t("market.info")}><Button type="text" icon={<InfoCircleOutlined />} aria-label={t("market.info")} disabled={!payload} onClick={() => setInfoOpen(true)} /></Tooltip><Tooltip title={t("market.fullscreen")}><Button type="text" icon={<FullscreenOutlined />} aria-label={t("market.fullscreen")} onClick={() => { void chartCard.current?.requestFullscreen().catch(() => undefined); }} /></Tooltip><Tooltip title={t("market.settings")}><Button type="text" icon={<SettingOutlined />} aria-label={t("market.settings")} onClick={openSettings} /></Tooltip></div>
      </header>
      <div className="tr-market-frame" aria-busy={loading}>
        {bars.length ? <MarketChart bars={bars} hasOI={!!payload?.has_oi} zone={zone} bands={bands} selectedBand={selectedBand} onUnavailable={onUnavailable} /> : <div className="tr-market-empty"><Empty description={error || (loading ? t("market.loading") : t("market.noData"))} /></div>}
        {loading ? <div className="tr-market-loading" role="status"><Spin /><span>{t("market.loading")}</span></div> : null}
      </div>
    </section>
    {termError ? <Alert type="error" message={termError} /> : null}
    {termAvailable ? <section className="tr-product-terms"><h2>{t("market.terms")}</h2><TRDataTable rows={contracts.slice((page - 1) * size, page * size)} rowKey={(row) => row.uid || `${row.contract}:${row.start}:${row.end}`} onRow={(row) => ({ onClick: () => setSelectedBand(String(row.uid || row.contract || `${row.start}:${row.end}`)) })} rowSelection={{ type: "radio", selectedRowKeys: selectedBand ? [selectedBand] : [], onSelect: (row) => setSelectedBand(String(row.uid || row.contract || `${row.start}:${row.end}`)) }} pagination={{ page, pageSize: size, total: contracts.length, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("market.identifier"), key: "identifier", render: (_, row) => <button className="tr-table-link" onClick={(event) => { event.stopPropagation(); instance.open("product-detail", { productName: product, contractUid: row.uid || row.contract, productTitle: row.contract || row.uid }); }}>{row.contract || row.uid}</button> },
      { title: t("market.start"), dataIndex: "start" }, { title: t("market.end"), dataIndex: "end" },
      { title: t("market.data"), key: "data", render: (_, row) => row.available_freqs?.length ? row.available_freqs.join(" · ") : t("market.noData") },
      ...["forward_adjustment_mul", "forward_adjustment_add", "backward_adjustment_mul", "backward_adjustment_add", "adjustment_ratio"].map((key) => ({ key, title: t(`market.${key}`), dataIndex: key, render: (value: unknown) => value ?? "—" })),
    ]} /></section> : null}
    <Collapse className="tr-product-fields" items={[{ key: "fields", label: t("market.fields"), children: fieldsError ? <Alert type="error" message={fieldsError} /> : <ProductFieldTable fields={fields} /> }]} />
    {settingsOpen ? <DetailsPanel title={t("market.settings")} onClose={() => { if (!loading) setSettingsOpen(false); }}><div className="tr-market-settings">
      {settingsError ? <Alert type="error" message={settingsError} /> : null}
      <label><span>{t("market.source")}</span><Select aria-label={t("market.source")} value={draft.source} options={[{ value: "", label: t("market.auto") }, ...sources.map((item) => ({ value: item.alias, label: [item.alias, item.freq, item.delivery_mode === "live_stream" ? t("market.live") : ""].filter(Boolean).join(" · ") })), ...nodeInputs.map(({value,label}) => ({value,label}))]} onChange={(value) => { const node = nodeInputs.find(item => item.value === value); setDraft((old) => ({ ...old, source: value, nodeSource: node?.binding, ...(node && old.range === "all" ? {range:"month"} : {}) })); }} /></label>
      <label><span>{t("market.adjustment")}</span><Select aria-label={t("market.adjustment")} disabled={!!contract || payload?.supports_adjusted === false} value={draft.adjusted ? "adjusted" : "raw"} options={[{ value: "raw", label: t("market.raw") }, { value: "adjusted", label: t("market.adjusted") }]} onChange={(value) => setDraft((old) => ({ ...old, adjusted: value === "adjusted" }))} /></label>
      <label><span>{t("market.frequency")}</span><Select aria-label={t("market.frequency")} value={draft.interval} options={[...intervals, ...(live ? ["LIVE"] : [])].map((value) => ({ value, label: t(`market.intervals.${value}`) }))} onChange={(value) => setDraft((old) => ({ ...old, interval: value }))} /></label>
      <label><span>{t("market.range")}</span><Select aria-label={t("market.range")} value={draft.range} options={["day", "month", "year", "ytd", "all", "custom"].map((value) => ({ value, label: t(`market.ranges.${value}`) }))} onChange={(value) => setDraft((old) => ({ ...old, range: value }))} /></label>
      {draft.range === "custom" ? <><label><span>{t("market.start")}</span><input type="date" aria-label={t("market.start")} value={draft.start || ""} onChange={(event) => setDraft((old) => ({ ...old, start: event.target.value }))} /></label><label><span>{t("market.end")}</span><input type="date" aria-label={t("market.end")} value={draft.end || ""} onChange={(event) => setDraft((old) => ({ ...old, end: event.target.value }))} /></label></> : null}
      <label><span>{t("market.timeZone")}</span><Select aria-label={t("market.timeZone")} value={draft.zone} options={[{ value: "product", label: `${t("market.productZone")} · ${payload?.timezone || zone}` }, { value: "system", label: `${t("market.systemZone")} · ${Intl.DateTimeFormat().resolvedOptions().timeZone}` }, { value: "utc", label: "UTC" }]} onChange={(value) => setDraft((old) => ({ ...old, zone: value }))} /></label>
      <footer><Button disabled={loading} onClick={() => setSettingsOpen(false)}>{t("configuration.cancel")}</Button><Button type="primary" loading={loading} onClick={saveSettings}>{t("market.saveLoad")}</Button></footer>
    </div></DetailsPanel> : null}
    {infoOpen ? <DetailsPanel title={t("market.info")} onClose={() => setInfoOpen(false)}><ResultView value={metadata} /></DetailsPanel> : null}
  </FunctionPage>;
}

function ProductFieldTable({ fields }: { fields: unknown }): React.ReactElement {
  const { t } = useTranslation();
  const rows = useMemo(() => productFieldRows(fields), [fields]);
  const [page, setPage] = useState(1), [size, setSize] = useState(15);
  const current = Math.min(page, Math.max(1, Math.ceil(rows.length / size)));
  return <TRDataTable rows={rows.slice((current-1)*size, current*size)} rowKey="key"
    pagination={{page:current,pageSize:size,total:rows.length,hideOnSinglePage:true,onChange:(p,s) => {setPage(p);setSize(s);}}}
    columns={[
      {key:"field",title:t("instrumentFields.field"),render:(_,row) => <><span>{t(`instrumentFields.labels.${row.key}`, {defaultValue:row.label || row.key})}</span><small className="tr-library-row-meta"><code>{row.key}</code></small></>},
      {key:"value",title:t("instrumentFields.value"),render:(_,row) => row.value === null || row.value === undefined ? t("properties.unknown") : typeof row.value === "object" ? <ResultView value={row.value} /> : String(row.value)},
      {dataIndex:"type",title:t("instrumentFields.type")},
      {key:"source",title:t("instrumentFields.source"),render:(_,row) => row.source || "—"},
    ]} />;
}
