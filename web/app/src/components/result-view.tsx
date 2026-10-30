import React, { useState } from "react";
import { Collapse, Empty } from "antd";
import { useTranslation } from "react-i18next";
import { TRDataTable } from "./data-table.tsx";
import { referenceForField } from "../object-reference.ts";
import { ObjectReference } from "./object-reference.tsx";

function ScalarValue({ field, value, record }: { field: string; value: unknown; record?: Record<string, unknown> }): React.ReactElement {
  const reference = referenceForField(field, value, record);
  return reference ? <ObjectReference value={reference} /> : <>{String(value ?? "—")}</>;
}
export function ResultView({ value, depth = 0, field = "value" }: { value: unknown; depth?: number; field?: string }): React.ReactElement {
  const { t } = useTranslation();
  if (value === null || value === undefined) return <Empty description={t("empty")} />;
  if (Array.isArray(value)) {
    if (!value.length) return <span className="tr-value-empty">{t("properties.none")}</span>;
    if (value.length <= 20 && value.every(item => item === null || typeof item !== "object")) return <ul className="tr-scalar-values">{value.map((item,index) => <li key={index}><ScalarValue field={field} value={item} /></li>)}</ul>;
    return <ResultArray value={value} field={field} />;
  }
  if (typeof value !== "object") return <span>{String(value)}</span>;
  const entries = Object.entries(value);
  if (!entries.length) return <span className="tr-value-empty">{t("properties.none")}</span>;
  const scalars = entries.filter(([, item]) => item === null || typeof item !== "object");
  const nested = entries.filter(([, item]) => item !== null && typeof item === "object");
  return <div className="tr-result-view">{scalars.length ? <dl className="tr-record-values">{scalars.map(([key,item]) => <div key={key}><dt>{key}</dt><dd><ScalarValue field={key} value={item} record={value as Record<string, unknown>} /></dd></div>)}</dl> : null}
    {nested.length ? <Collapse ghost defaultActiveKey={depth < 1 ? nested.slice(0, 2).map(([key]) => key) : []} items={nested.map(([key, item]) => ({ key, label: key,
      children: depth < 6 ? <ResultView value={item} depth={depth + 1} field={key} /> : <pre className="tr-job-detail">{JSON.stringify(item, null, 2)}</pre> }))} /> : null}</div>;
}
function CellDetails({value}:{value:unknown}):React.ReactElement {
 const {t}=useTranslation();const [open,setOpen]=useState(false);
 return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>{t("details")}</summary>{open ? <ResultView value={value} /> : null}</details>;
}
function ResultArray({ value, field }: { value: unknown[]; field: string }): React.ReactElement {
  const { t } = useTranslation(); const [page, setPage] = useState(1), [size, setSize] = useState(20);
  const current = Math.min(page, Math.max(1, Math.ceil(value.length / size))), offset=(current-1)*size;
  const rows=value.slice(offset,offset+size).map((item,index) => ({id:offset+index,value:item}));
  const keys=[...new Set(rows.flatMap(row => row.value !== null && typeof row.value === "object" ? Object.keys(row.value) : ["value"]))];
  return <TRDataTable<{id:number;value:unknown}> rows={rows} rowKey="id" pagination={{page:current,pageSize:size,total:value.length,hideOnSinglePage:true,onChange:(p,s) => {setPage(p);setSize(s);}}}
    columns={keys.map(key => ({key,title:key,render:(_,row) => {
      const item=row.value !== null && typeof row.value === "object" ? (row.value as Record<string,unknown>)[key] : key==="value" ? row.value : undefined;
      return item !== null && typeof item === "object" ? <CellDetails value={item} /> : <ScalarValue field={key === "value" ? field : key} value={item} record={row.value !== null && typeof row.value === "object" ? row.value as Record<string, unknown> : undefined} />;
    }}))} />;
}
