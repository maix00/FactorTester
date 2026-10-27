import React, { useEffect, useState } from "react";
import { Alert, Button, Spin, Tag } from "antd";
import { InfoCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { usePageInstance } from "../page-instance.ts";
import { PropertyGroups, type PropertyItem } from "../components/property-groups.tsx";
import { request } from "../configuration/api.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { bookTypes, sourceCapability, sourceIdentity, sourceTitle, type SourceRow } from "../source-model.ts";
function Value({value}: {value:unknown}): React.ReactElement {
 const {t}=useTranslation();
 if (value === null || value === undefined || value === "") return <>—</>;
 if (typeof value === "boolean") return <>{t(value ? "sources.yes" : "sources.no")}</>;
 if (Array.isArray(value)) return <>{value.map(String).join(" · ") || t("sources.none")}</>;
 if (typeof value === "object" && !Object.keys(value).length) return <>{t("sources.none")}</>;
 if (typeof value === "object") return <dl className="tr-source-mapping">{Object.entries(value).map(([key,item]) => <div key={key}><dt>{key}</dt><dd>{String(item)}</dd></div>)}</dl>;
 return <>{String(value)}</>;
}
export function SourceDetailPage(): React.ReactElement {
 const {t,i18n}=useTranslation(),instance=usePageInstance(),id=instance.args.sourceFamilyId || "";
 const [source,setSource]=useState<SourceRow|null>(null),[error,setError]=useState(""),[revision,setRevision]=useState(0);
 const [selected,setSelected]=useState<SourceRow|null>(null),[page,setPage]=useState(1),[size,setSize]=useState(15);
 useEffect(() => { const abort=new AbortController();setSource(null);setError("");setSelected(null);
  void request("/api/product-library/data-sources",{signal:abort.signal}).then(data => {if(abort.signal.aborted)return;const found=(data.sources || []).find((row:SourceRow) => sourceIdentity(row).toLowerCase()===id.toLowerCase());if(!found)throw new Error(t("sources.notFound"));setSource(found);}).catch(reason => {if(!abort.signal.aborted)setError(reason.message);});return () => abort.abort();
 },[id,revision]);
 const members:SourceRow[]=source?.members || [];
 const status=(value:unknown):string => t(`sources.status.${value}`,{defaultValue:t("sources.unknown")});
 return <FunctionPage title={source ? sourceTitle(source) : t("sources.title")} actions={<Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => {setPage(1);setRevision(value => value+1);}} />}>
 {error ? <Alert type="error" message={error} /> : !source ? <Spin /> : <>
 <div className="tr-source-summary"><Tag>{source.provider_kind || "—"}</Tag><span>{sourceIdentity(source)}</span></div>
 <div className="tr-source-overview"><PropertyGroups groups={[
 {key:"coverage",title:t("sources.groups.coverage"),items:[
  {key:"frequency",label:t("sources.frequencies"),value:source.availability?.frequency_names || source.data_modes?.map((mode:SourceRow) => mode.id),render:value => <Value value={value} />},
  {key:"products",label:t("sources.products"),value:source.availability?.product_count},
  {key:"catalog",label:t("sources.catalogProducts"),value:source.catalog_product_count},
  {key:"status",label:t("sources.availability"),value:source.availability?.status,render:value => status(value)},
  {key:"categories",label:t("catalog.categories"),value:source.categories?.map((item:SourceRow) => (i18n.resolvedLanguage?.startsWith("zh") ? item.title_zh : item.title_en) || item.title || item.id),render:value => <Value value={value} />},
  {key:"paths",label:t("sources.paths"),value:source.product_paths,render:value => <Value value={value} />},
 ]},
 {key:"access",title:t("sources.groups.access"),items:[
  {key:"server",label:t("sources.serverProvided"),value:source.server_provided,render:value => t(value ? "sources.yes" : "sources.no")},
  {key:"access",label:t("sources.visitor"),value:source.visitor_data_accessible,render:value => t(value ? "sources.allowed" : "sources.denied")},
 ]},
 ]} /></div>
 <section className="tr-source-members"><h2>{t("sources.members")}</h2><TRDataTable rows={members.slice((page-1)*size,page*size)} rowKey={row => row.key || row.id} pagination={{page,pageSize:size,total:members.length,onChange:(p,s) => {setPage(p);setSize(s);}}} columns={[
 {key:"name",title:t("sources.member"),render:(_,row) => <button className="tr-table-link" onClick={() => setSelected(row)}>{row.label || row.id}<small className="tr-library-row-meta">{row.id}</small></button>},
 {dataIndex:"frequency",title:t("sources.frequencies")},
 {key:"kind",title:t("sources.dataKind"),render:(_,row) => row.dimensions?.data_kind || row.data_modes?.[0]?.data_kind || "—"},
 {key:"depth",title:t("sources.depth"),render:(_,row) => row.dimensions?.market_depth || row.data_modes?.[0]?.market_depth || "—"},
 {dataIndex:"product_count",title:t("sources.products"),render:value => value ?? "—"},
 {key:"status",title:t("sources.availability"),render:(_,row) => status(row.availability?.status)},
 {key:"info",title:t("details"),render:(_,row) => <Button type="text" icon={<InfoCircleOutlined />} aria-label={`${t("sources.properties")} · ${row.label || row.id}`} onClick={() => setSelected(row)} />},
 ]} /></section>
 {selected ? <DetailsPanel width={640} title={selected.label || selected.id} onClose={() => setSelected(null)}><SourceProperties member={selected} /></DetailsPanel> : null}
 </>}
 </FunctionPage>;
}
function SourceProperties({member}:{member:SourceRow}):React.ReactElement {
 const {t}=useTranslation();const [capabilities,setCapabilities]=useState<SourceRow|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState("");
 useEffect(() => {const abort=new AbortController();void request("/api/nautilus/capabilities",{signal:abort.signal}).then(data => {if(!abort.signal.aborted){setCapabilities(data);if(data.market_data_sources?.available===false)setError(data.market_data_sources.reason || t("sources.capabilityUnavailable"));}}).catch(reason => {if(!abort.signal.aborted)setError(reason.message);}).finally(() => {if(!abort.signal.aborted)setLoading(false);});return () => abort.abort();},[]);
 const {value:capability,origin}=sourceCapability(member,capabilities),dimensions=member.dimensions || member.data_modes?.[0] || {};
 const item=(key:string):PropertyItem => ({key,wide:key === "time_columns" || key === "data_columns",label:t(`sources.fields.${key}`),value:capability?.[key] ?? dimensions[key] ?? member[key],render:value => <Value value={value} />});
 const adapter=capability?.adapter_available;
 const adapterLabel=adapter===true ? t("sources.validated") : adapter===false ? t("sources.notAdapted") : t("sources.unknown");
 return <div className="tr-source-properties">{loading ? <Spin /> : null}{error ? <Alert type="warning" message={t("sources.capabilityUnavailable")} description={error} /> : null}
 <div className="tr-source-property-meta"><code>{member.id || member.key}</code><span>{t(`sources.origins.${origin}`)}</span></div>
 <div className={`tr-source-adapter-status ${adapter===true ? "is-ready" : adapter===false ? "is-unavailable" : ""}`}><span aria-hidden="true" />{adapterLabel}</div>
 <PropertyGroups groups={[
  {key:"data",title:t("sources.groups.data"),items:[{key:"frequency",label:t("sources.frequencies"),value:capability?.frequency ?? member.frequency},...['mode_available','data_kind','market_depth','delivery_mode','sampling_mode','supported_book_types'].map(item)]},
  {key:"time",title:t("sources.groups.time"),items:['timezone','bar_time_semantics','raw_timestamp_unit','layout','naming_scheme'].map(item)},
  {key:"mapping",title:t("sources.groups.mapping"),items:['time_columns','data_columns'].map(item)},
  {key:"adapter",title:t("sources.groups.engine"),items:[...['adapter_id','instrument_scope','reason'].map(item),{key:"books",label:t("sources.configurableBooks"),value:capabilities?.simulated_venue_config ? bookTypes(capabilities) : undefined,render:value => <Value value={value} />}]},
 ]} /></div>;
}
