import React, { useEffect, useState } from "react";
import { Alert, Button, Descriptions, Spin, Tag } from "antd";
import { InfoCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { usePageInstance } from "../page-instance.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { request } from "../configuration/api.ts";
import { FunctionPage } from "../components/function-page.tsx";
import { DetailsPanel } from "../components/details-panel.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { bookTypes, sourceCapability, sourceIdentity, sourceTitle, type SourceRow } from "../source-model.ts";
function Value({value}: {value:unknown}): React.ReactElement {
 if (value === null || value === undefined || value === "") return <>—</>;
 if (Array.isArray(value)) return <>{value.map(String).join(" · ") || "—"}</>;
 if (typeof value === "object") return <dl className="tr-source-mapping">{Object.entries(value).map(([key,item]) => <div key={key}><dt>{key}</dt><dd>{String(item)}</dd></div>)}</dl>;
 return <>{String(value)}</>;
}
export function SourceDetailPage(): React.ReactElement {
 const {t,i18n}=useTranslation(),mobile=useCompactLayout(),instance=usePageInstance(),id=instance.args.sourceFamilyId || "";
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
 <Descriptions className="tr-source-overview" bordered size="small" column={1} layout={mobile ? "vertical" : "horizontal"} items={[
  {key:"server",label:t("sources.serverProvided"),children:source.server_provided===true ? t("sources.yes") : source.server_provided===false ? t("sources.no") : t("sources.unknown")},
  {key:"categories",label:t("catalog.categories"),children:<Value value={source.categories?.map((item:SourceRow) => (i18n.resolvedLanguage?.startsWith("zh") ? item.title_zh : item.title_en) || item.title || item.id)} />},
  {key:"frequency",label:t("sources.frequencies"),children:<Value value={source.availability?.frequency_names || source.data_modes?.map((mode:SourceRow) => mode.id)} />},
  {key:"products",label:t("sources.products"),children:source.availability?.product_count ?? "—"},
  {key:"catalog",label:t("sources.catalogProducts"),children:source.catalog_product_count ?? "—"},
  {key:"status",label:t("sources.availability"),children:status(source.availability?.status)},
  {key:"paths",label:t("sources.paths"),children:<Value value={source.product_paths} />},
  {key:"access",label:t("sources.visitor"),children:source.visitor_data_accessible===true ? t("sources.allowed") : source.visitor_data_accessible===false ? t("sources.denied") : t("sources.unknown")},
 ]} />
 <section className="tr-source-members"><h2>{t("sources.members")}</h2><TRDataTable rows={members.slice((page-1)*size,page*size)} rowKey={row => row.key || row.id} pagination={{page,pageSize:size,total:members.length,onChange:(p,s) => {setPage(p);setSize(s);}}} columns={[
 {key:"name",title:t("sources.member"),render:(_,row) => <button className="tr-table-link" onClick={() => setSelected(row)}>{row.label || row.id}<small className="tr-library-row-meta">{row.id}</small></button>},
 {dataIndex:"frequency",title:t("sources.frequencies")},
 {key:"kind",title:t("sources.dataKind"),render:(_,row) => row.dimensions?.data_kind || row.data_modes?.[0]?.data_kind || "—"},
 {key:"depth",title:t("sources.depth"),render:(_,row) => row.dimensions?.market_depth || row.data_modes?.[0]?.market_depth || "—"},
 {dataIndex:"product_count",title:t("sources.products"),render:value => value ?? "—"},
 {key:"status",title:t("sources.availability"),render:(_,row) => status(row.availability?.status)},
 {key:"info",title:t("details"),render:(_,row) => <Button type="text" icon={<InfoCircleOutlined />} aria-label={`${t("sources.properties")} · ${row.label || row.id}`} onClick={() => setSelected(row)} />},
 ]} /></section>
 {selected ? <DetailsPanel title={selected.label || selected.id} onClose={() => setSelected(null)}><SourceProperties member={selected} /></DetailsPanel> : null}
 </>}
 </FunctionPage>;
}
function SourceProperties({member}:{member:SourceRow}):React.ReactElement {
 const {t}=useTranslation(),mobile=useCompactLayout();const [capabilities,setCapabilities]=useState<SourceRow|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState("");
 useEffect(() => {const abort=new AbortController();void request("/api/nautilus/capabilities",{signal:abort.signal}).then(data => {if(!abort.signal.aborted){setCapabilities(data);if(data.market_data_sources?.available===false)setError(data.market_data_sources.reason || t("sources.capabilityUnavailable"));}}).catch(reason => {if(!abort.signal.aborted)setError(reason.message);}).finally(() => {if(!abort.signal.aborted)setLoading(false);});return () => abort.abort();},[]);
 const {value:capability,origin}=sourceCapability(member,capabilities),dimensions=member.dimensions || member.data_modes?.[0] || {};
 const keys=["sampling_mode","data_kind","market_depth","delivery_mode","supported_book_types","adapter_id","instrument_scope","timezone","bar_time_semantics","raw_timestamp_unit","layout","naming_scheme","time_columns","data_columns","reason"];
 return <div className="tr-source-properties">{loading ? <Spin /> : null}{error ? <Alert type="warning" message={t("sources.capabilityUnavailable")} description={error} /> : null}
 <Tag>{t(`sources.origins.${origin}`)}</Tag><Descriptions bordered size="small" column={1} layout={mobile ? "vertical" : "horizontal"} items={[
 {key:"adapter",label:t("sources.adapterStatus"),children:capability?.adapter_available===true ? t("sources.validated") : capability?.adapter_available===false ? t("sources.notAdapted") : t("sources.unknown")},
 ...keys.map(key => ({key,label:t(`sources.fields.${key}`),children:<Value value={capability?.[key] ?? dimensions[key] ?? member[key]} />})),
 {key:"books",label:t("sources.configurableBooks"),children:<Value value={bookTypes(capabilities)} />},
 ]} /></div>;
}
