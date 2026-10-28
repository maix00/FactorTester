import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Empty, Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { loadFactorModel, factorIndicators, observationBounds, type FactorModel } from "../charts/factor-result.ts";
import { loadChartRuntime, type MarketBar } from "../charts/runtime.ts";
import { readJobArtifact } from "../artifacts.ts";
import type { JobReference } from "../job-model.ts";
import { request } from "../configuration/api.ts";
import { Formula } from "./formula.tsx";
export function FactorResults({ result, artifactName, job, configuration }: { result: unknown; artifactName?: string; job: JobReference; configuration: unknown }): React.ReactElement {
  const { t } = useTranslation();
  const [model, setModel] = useState<FactorModel | null>(null), [product, setProduct] = useState("");
  const [bars, setBars] = useState<MarketBar[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState(""), [priceError, setPriceError] = useState("");
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError(""); setModel(null);
    void (async () => {
      const api = await loadFactorModel(); let parsed = api.build(result);
      if (!parsed.series.length && artifactName) { const blob = await readJobArtifact(job, artifactName, abort.signal); parsed = api.build(JSON.parse(await blob.text())); }
      if (abort.signal.aborted) return;
      setModel(parsed); setProduct(parsed.series.length ? api.productIdentity(parsed.series[0]) : "");
    })().catch((cause) => { if (!abort.signal.aborted) setError(cause.message); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [result, artifactName, job.job_id, job.server_id, job.service_port]);
  const layers = useMemo(() => model?.series.filter((item) => window.FTFactorSeriesModel?.productIdentity(item) === product) || [], [model, product]);
  const products = useMemo(() => [...new Set(model?.series.map((item) => window.FTFactorSeriesModel!.productIdentity(item)) || [])], [model]);
  useEffect(() => {
    if (!model || !product) return;
    const abort = new AbortController(); setLoading(true); setPriceError(""); setBars([]);
    void (async () => {
      await loadChartRuntime();
      const frozen = window.FTFactorSeriesModel!.priceRequest(configuration, product, model.factor.freq);
      const bounds = observationBounds(layers, window.FTPriceChart!.timestampOf);
      const body = { ...frozen, start_date: frozen.start_date || bounds.start_date, end_date: frozen.end_date || bounds.end_date, chart_mode: "fixed", chart_interval: "SOURCE", max_points: 5000 };
      const payload = await request("/api/market-data/prices", {method:"POST",body:JSON.stringify(body),signal:abort.signal});
      if (!abort.signal.aborted) setBars(window.FTPriceChart!.barsOf(payload));
    })().catch((cause) => { if (!abort.signal.aborted) setPriceError(cause.message); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [model, product, configuration, layers]);
  useEffect(() => {
    if (!model || !layers.length || loading || !host.current) return;
    let cancelled = false, dispose: (() => void) | undefined;
    void loadChartRuntime().then(() => {
      if (cancelled || !host.current) return;
      dispose = window.FTChartWorkbench!.mountFactorChart(host.current, { bars, indicators: factorIndicators(layers, window.FTPriceChart!.timestampOf), product, loadRange: async () => null,
        translate: (value) => ({"因子指标":t("factorResults.layers"),"价格与因子指标":t("factorResults.chart"),"开盘价":t("market.open"),"最高价":t("market.high"),"最低价":t("market.low"),"收盘价":t("market.close"),"成交量":t("market.volume"),"持仓量":t("market.openInterest")} as Record<string,string>)[value] || value }).dispose;
    }).catch((cause) => { if (!cancelled) setError(cause.message); });
    return () => { cancelled = true; if (dispose) queueMicrotask(dispose); };
  }, [bars, layers, loading, product, model, t]);
  if (error) return <Alert type="error" message={error} />;
  if (!model) return <Spin />;
  if (!model.series.length) return <Empty description={t("empty")} />;
  return <section className="tr-factor-results">
    <header><h2>{t("factorResults.title")}</h2><Select aria-label={t("factorResults.product")} value={product} options={products.map((value) => ({value,label:value}))} onChange={setProduct} /></header>
    {priceError ? <Alert type="warning" message={t("factorResults.priceUnavailable")} description={priceError} /> : null}
    <div className="tr-factor-result-formulas">{layers.map((item,index) => <div key={index}><span className="tr-factor-index">F{index+1}</span><span>{item.layer || item.factor_alias || model.factor.alias}</span>{item.math_expr ? <Formula latex={item.math_expr} /> : null}</div>)}</div>
    <div className="tr-chart-host tr-factor-result-chart"><div ref={host} />{loading ? <div className="tr-market-loading" role="status"><Spin /><span>{t("market.loading")}</span></div> : null}</div>
  </section>;
}
