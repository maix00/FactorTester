import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Select, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { ReloadOutlined } from "@ant-design/icons";
import { request } from "./api.ts";
import { automaticExecutionRequest, executionRequest, type ExecutionSelection, type ExecutionTarget } from "./execution-target-model.ts";
import "./execution-target.css";

const offerKey = (offer: ExecutionTarget["offers"][number]): string => JSON.stringify([offer.source_ref, offer.product_ref, offer.bar_spec]);
const semanticKey = (offer: ExecutionTarget["offers"][number]): string => JSON.stringify([offer.product_ref, offer.bar_spec, offer.price_basis, offer.time_semantics, [...offer.fields].sort()]);

export function ExecutionTargetPicker({ analysis, onChange, onCapabilities }: {
  analysis: string;
  onCapabilities: (types: string[]) => void;
  onChange: (selection: ExecutionSelection | null, required: boolean) => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const [managers, setManagers] = useState<string[]>([]), [manager, setManager] = useState("");
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [targets, setTargets] = useState<ExecutionTarget[]>([]), [selected, setSelected] = useState("");
  const [sources, setSources] = useState<string[]>([]), [start, setStart] = useState(""), [end, setEnd] = useState("");
  const [reload, setReload] = useState(0), [loading, setLoading] = useState(false), [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    request("/api/federation/servers", {signal:controller.signal}).then(value => {
      if (controller.signal.aborted) return;
      setManagers([...new Set([value.server_id, ...(value.servers || []).map((item: {server_id:string}) => item.server_id)])].filter(Boolean) as string[]);
      setManager(value.server_id || "");
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!manager) return;
    const controller = new AbortController(); setLoading(true); setTargets([]);
    request(`/api/test-authoring/execution-targets?server_id=${encodeURIComponent(manager)}`, {signal:controller.signal}).then(value => {
      if (!controller.signal.aborted) { setTargets(value.targets || []); setError(""); }
    }).catch(reason => { if (!controller.signal.aborted) { setError(reason.message); setTargets([]); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload, manager]);

  const target = targets.find(item => item.route_id === selected && item.online);
  const automaticTargets = useMemo(() => targets.filter(item => item.online), [targets]);
  const types = useMemo(() => mode === "manual" ? target?.target.test_types || [] :
    [...new Set(automaticTargets.flatMap(item => item.target.test_types))].sort(), [mode, target, automaticTargets]);
  useEffect(() => { onCapabilities(types); }, [types, onCapabilities]);
  const offers = useMemo(() => mode === "manual" ? target?.offers || [] :
    [...new Map(automaticTargets.filter(item => item.target.test_types.includes(analysis)).flatMap(item => item.offers)
      .filter(offer => offer.available).map(offer => [semanticKey(offer), offer])).values()], [mode, target, automaticTargets, analysis]);
  const choice = useMemo(() => {
    const selectedOffers = offers.filter(offer => sources.includes(mode === "auto" ? semanticKey(offer) : offerKey(offer)));
    try {
      return mode === "auto" ? automaticExecutionRequest(selectedOffers, start, end, analysis, manager) :
        target ? executionRequest(target, selectedOffers, start, end, analysis) : null;
    } catch { return null; }
  }, [mode, target, offers, sources, start, end, analysis, manager]);
  useEffect(() => { onChange(choice, true); }, [choice, onChange]);

  return <section className="tr-execution-target" aria-label={t("executionTopology.title")}>
    <div className="tr-execution-heading"><h2>{t("executionTopology.title")}</h2><Button type="text" icon={<ReloadOutlined />} aria-label={t("executionTopology.refresh")} loading={loading} onClick={() => { onChange(null,true); setTargets([]); setReload(value => value + 1); }} /></div>
    <label className="tr-execution-row"><span>{t("executionTopology.mode")}</span><Select value={mode} options={[{value:"auto",label:t("executionTopology.auto")},{value:"manual",label:t("executionTopology.manual")}]} onChange={value => {setMode(value);setSources([]);onChange(null,true);}} /></label>
    <label className="tr-execution-row"><span>Manager</span><Select aria-label="Manager" value={manager || undefined} options={managers.map(value => ({value,label:value}))} onChange={value => {setManager(value);setSelected("");setSources([]);setTargets([]);onChange(null,true);}} /></label>
    {mode === "manual" ? <label className="tr-execution-row"><span>{t("executionTopology.service")}</span><Select showSearch optionFilterProp="label" allowClear loading={loading} value={selected || undefined} placeholder={t("executionTopology.chooseService")} onChange={value => {setSelected(value || "");setSources([]);onChange(null,true);}} options={targets.map(item => ({value:item.route_id,disabled:!item.online,label:`${item.target.node_id} · ${item.target.service_id} · ${item.target.deployment_ref}${item.online ? "" : ` · ${t("executionTopology.offline")}`}`}))} /></label> : <Typography.Text type="secondary">{t("executionTopology.autoHint")}</Typography.Text>}
    {types.length ? <Typography.Text type="secondary">{types.map(type => t(`configuration.analysisNames.${type}`,{defaultValue:type})).join(" · ")}</Typography.Text> : null}
    {offers.length ? <>
      <label className="tr-execution-row"><span>{t(mode === "auto" ? "executionTopology.requirements" : "executionTopology.inputs")}</span><Select mode="multiple" showSearch optionFilterProp="label" value={sources} onChange={setSources} options={offers.map(offer => ({value:mode === "auto" ? semanticKey(offer) : offerKey(offer),disabled:!offer.available,label:`${offer.product_ref} · ${offer.bar_spec} · ${offer.price_basis}${mode === "manual" ? ` · ${offer.installation.bundle_id}/${offer.installation.bundle_version}` : ""}`}))} /></label>
      <div className="tr-execution-dates"><label className="tr-execution-row"><span>{t("executionTopology.start")}</span><Input aria-label={t("executionTopology.start")} type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></label><label className="tr-execution-row"><span>{t("executionTopology.end")}</span><Input aria-label={t("executionTopology.end")} type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></label></div>
      <Typography.Text type="secondary">{t("executionTopology.hint")}</Typography.Text>
    </> : null}
    {!loading && !targets.length && !error ? <Typography.Text type="secondary">{t("executionTopology.none")}</Typography.Text> : null}
    {error ? <Alert type="error" showIcon message={error} /> : null}
  </section>;
}
