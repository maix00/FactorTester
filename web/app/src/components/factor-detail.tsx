import React, { useState } from "react";
import { Collapse, Empty } from "antd";
import { useTranslation } from "react-i18next";
import {factorParameterValues,parameterLabel} from "../factor-parameters.ts";
import {ObjectReference} from "./object-reference.tsx";
import { Formula } from "./formula.tsx";
import { ResultView } from "./result-view.tsx";
import { TRDataTable } from "./data-table.tsx";
export function FactorDetail({ detail }: { detail: Record<string, any> | null }): React.ReactElement {
  const { t } = useTranslation(); const [page, setPage] = useState(1), [size, setSize] = useState(10);
  if (!detail) return <Empty description={t("loading")} />;
  const factor = detail.factor || detail, family = detail.family || detail;
  const formula = factor.resolved_math_expr || family.math_expr;
  const definitions=family.parameter_definitions || family.params || [];
  const instance=!!detail.factor||String(factor.ref||factor.factor_ref||'').startsWith('factor:v2:');
  const values=instance?factorParameterValues(factor.identity?.params||factor.params):{};
  const params=[...(Array.isArray(definitions)?definitions:[])];
  if(instance)for(const alias of Object.keys(values))if(!params.some(row=>row.alias===alias))params.push({alias});
  const description = factor.description || family.description;
  return <div className="tr-factor-detail">
    {description ? <p className="tr-factor-description">{description}</p> : null}
    {typeof formula === "string" && formula ? <section><h3>{t("library.formula")}</h3><Formula latex={formula} /></section> : null}
    {Array.isArray(params) && params.length ? <section><h3>{t("editor.parameters")}</h3><TRDataTable rows={params.slice((page - 1) * size, page * size)} rowKey={(row) => row.alias || row.name} pagination={{ page, pageSize: size, total: params.length, hideOnSinglePage: true, onChange: (p, s) => { setPage(p); setSize(s); } }} columns={[
      { title: t("editor.name"), key: "name", render: (_, row) => parameterLabel(row) },
      { title: t("library.type"), key: "type", render: (_, row) => row.value_type || row.type || "—" },
      { title: t("library.defaultValue"), key: "default", render: (_, row) => { const value = row.default_value ?? row.default; return value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value); } },
      ...(instance?[{title:t("instrumentFields.value"),key:"value",render:(_:unknown,row:Record<string,any>)=>{
        const value=values[row.alias],ref=typeof value==="string"&&value.startsWith("factor:v2:")?value:value&&typeof value==="object"?(value.ref||value.factor_ref):null;
        return ref?<ObjectReference value={{kind:"factor",ref:String(ref),label:typeof value==="object"?value.alias:undefined,owner:typeof value==="object"?value.owner_ref:undefined}}/>:value!==undefined?<ResultView value={value}/>:"—";
      }}]:[]),
      { title: t("library.description"), key: "description", render: (_, row) => row.desc || row.description || "—" },
    ]} /></section> : null}
    <Collapse ghost items={[{ key: "identity", label: t("library.identity"), children: <ResultView value={factor.identity || { factor_ref: factor.ref || factor.factor_ref, family_ref: family.family_ref, revision_ref: family.revision_ref }} /> }]} />
  </div>;
}
