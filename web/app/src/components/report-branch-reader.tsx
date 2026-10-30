import React, { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Select, Spin } from "antd";
import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { reportResourceURL, type ReportExportTarget } from "../report-export.ts";
import { reportReference, type ReportReference } from "../report-references.ts";
import { referenceForField, type ObjectKind } from "../object-reference.ts";
import { downloadBlob } from "../download.ts";
import { notify } from "../notifications/core.ts";
import { Formula, loadFormulaRenderer, type FormulaRenderer } from "./formula.tsx";
import { reportMarkdown } from "../report-markdown.ts";
import { ObjectReference, ObjectReferenceContext } from "./object-reference.tsx";
import { ResultView } from "./result-view.tsx";
import { TRDataTable } from "./data-table.tsx";
import { DetailsPanel } from "./details-panel.tsx";
import "./report-branch-reader.css";

type Row = Record<string, any>;

function Markdown({ value, onOpen }: { value: string; onOpen: (reference:ReportReference,label:string) => void }): React.ReactElement {
  const [engine,setEngine] = useState<FormulaRenderer | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!/[\$\\]/.test(value)) return;
    let active = true;
    void loadFormulaRenderer().then(result => {if (active) setEngine(result);}).catch(() => undefined);
    return () => {active = false;};
  }, [value]);
  const prepared = useMemo(() => {
    const formulas = new Map<string,{latex:string; options:Record<string,unknown>}>();
    const links = new Map<string,{reference:ReportReference; label:string}>();
    const nonce = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const placeholder: FormulaRenderer | null = engine ? {renderToString:(latex,options) => {
      const id = `${nonce}-${formulas.size}`; formulas.set(id,{latex,options});
      return `<span data-tr-formula="${id}"></span>`;
    }} : null;
    const html = DOMPurify.sanitize(reportMarkdown(value, placeholder, (href,label) => {
      const reference = reportReference(href);
      if (!reference) return null;
      const id = `${nonce}-${links.size}`; links.set(id,{reference,label}); return id;
    }), {
      FORBID_TAGS:["style","iframe","object","embed","form"], FORBID_ATTR:["style"],
    });
    return {html,formulas,links};
  }, [value,engine]);
  useLayoutEffect(() => {
    if (!engine || !root.current) return;
    for (const node of root.current.querySelectorAll<HTMLElement>("[data-tr-formula]")) {
      const formula = prepared.formulas.get(node.dataset.trFormula || "");
      if (formula && !node.hasChildNodes()) node.innerHTML = engine.renderToString(formula.latex, formula.options);
    }
    // React can restore the sanitized placeholders after a surrounding panel
    // changes; fill only empty placeholders before each paint.
  });
  return <div ref={root} className="tr-report-reading-text" onClick={event => {
    const element = (event.target as Element).closest?.("button[data-tr-report-link]") as HTMLButtonElement | null;
    const link = element && prepared.links.get(element.dataset.trReportLink || "");
    if (link) onOpen(link.reference,link.label);
  }} dangerouslySetInnerHTML={{__html:prepared.html}} />;
}

function ReportCell({ value, field = "", parent = {}, onOpen }: { value:unknown; field?:string; parent?:Row; onOpen:(reference:ReportReference,label:string) => void }): React.ReactElement {
  if (value && typeof value === "object") {
    const item = value as Row, target = String(item.target || item.href || item.url || item.reference || ""), label = String(item.label || item.title || item.text || item.filename || target);
    const reference = reportReference(target);
    if (reference) return <button type="button" className="tr-table-link tr-object-reference" onClick={() => onOpen(reference,label)}>{label}</button>;
    if (/^https?:\/\//i.test(target)) return <a href={target} target="_blank" rel="noopener noreferrer">{label}</a>;
    if (!target && typeof item.text === "string") return <ReportCell value={item.text} onOpen={onOpen} />;
    return <ResultView value={value} />;
  }
  const reference = referenceForField(field,value,parent);
  if (reference?.kind === "product") return <button type="button" className="tr-table-link tr-object-reference" onClick={() => onOpen({kind:"product",ref:reference.ref},reference.label || reference.ref)}>{reference.label || reference.ref}</button>;
  if (reference) return <ObjectReference value={reference} />;
  if (typeof value === "string" && /\[[^\]]+\]\(|\$|\\[([]/.test(value)) return <Markdown value={value} onOpen={onOpen} />;
  return <>{String(value ?? "—")}</>;
}

function ReportTable({ value, onOpen }: { value: unknown; onOpen:(reference:ReportReference,label:string) => void }): React.ReactElement {
  const [page,setPage] = useState(1), [size,setSize] = useState(20);
  const content = value && typeof value === "object" ? value as Row : {};
  const rows: unknown[] = Array.isArray(value) ? value : Array.isArray(content.rows) ? content.rows : [];
  const first = rows[0];
  const firstCells = Array.isArray(first) ? first : first && typeof first === "object" && Array.isArray((first as Row).cells) ? (first as Row).cells : null;
  const columns: any[] = Array.isArray(content.columns) ? content.columns : Array.isArray(content.headers) ? content.headers : firstCells ? firstCells.map((_:unknown,index:number) => String(index + 1)) : first && typeof first === "object" ? Object.keys(first) : [];
  const indexed = rows.slice((page-1)*size,page*size).map((row,index) => ({index:(page-1)*size+index,row}));
  return <TRDataTable rows={indexed} rowKey="index" pagination={{page,pageSize:size,total:rows.length,hideOnSinglePage:true,onChange:(next,nextSize) => {setPage(next);setSize(nextSize);}}} columns={columns.map((column,index) => ({
    key:String(typeof column === "object" ? column.key || index : column),title:String(typeof column === "object" ? column.title || column.label || column.key || "" : column),
    render:(_:unknown,item:{index:number;row:unknown}) => {
      const row = item.row as any;
      const cell = Array.isArray(row) ? row[index] : Array.isArray(row?.cells) ? row.cells[index] : row?.[typeof column === "object" ? column.key : column];
      return <ReportCell value={cell} field={String(typeof column === "object" ? column.key || "" : column)} parent={row && !Array.isArray(row) && typeof row === "object" ? row : {}} onOpen={onOpen} />;
    },
  }))} />;
}

function ReportBlock({ component, assets, bindings, resources, target }: { component: Row; assets: Row[]; bindings: Row[]; resources: Row[]; target: ReportExportTarget }): React.ReactElement {
  const { t } = useTranslation();
  const openObject = useContext(ObjectReferenceContext), [referenceDetail,setReferenceDetail] = useState<Row | null>(null);
  const pending = useRef(false);
  const kind = String(component.kind || ""), body = typeof component.body === "string" ? component.body : "", content = component.content;
  const assetRef = content && typeof content === "object" ? String(content.asset_id || content.asset_ref || "") : "";
  const asset = assets.find(item => [item.asset_id,item.asset_ref,item.external_ref,item.filename].some(value => value === assetRef));
  const assetID = String(asset?.asset_id || asset?.asset_ref || "");
  const assetURL = assetID ? reportResourceURL(target,["assets",assetID]) : null;
  const entries: any[] = Array.isArray(content) ? content : Array.isArray(content?.items) ? content.items : Array.isArray(content?.rows) ? content.rows : [];
  const title = String(component.title || "");
  const openReference = (reference:ReportReference,label:string): void => {
    if (pending.current) return;
    const binding = bindings.find(item => String(item.kind || "").replaceAll("-","_") === reference.kind && String(item.target_ref || "") === reference.ref);
    void (async () => {
      pending.current = true;
      try {
        if (reference.kind === "local_resource") {
          const resource = resources.find(item => item.resource_id === reference.ref);
          const url = resource && reportResourceURL(target,["local-resources",reference.ref],{inline:"1"});
          if (!resource || !url) throw new Error(t("report.imageUnavailable"));
          const response = await fetch(url,{credentials:"same-origin",redirect:"error"});
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          downloadBlob(await response.blob(),String(resource.filename || label || reference.ref));
          return;
        }
        const kinds: Record<string,ObjectKind> = {factor:"factor",factor_family:"factorFamily",strategy:"strategy",strategy_family:"strategyFamily",profile:"profile",user:"user",product_group:"productGroup"};
        if (reference.kind === "product" && openObject) {
          const query = new URLSearchParams({kind:"product",target_ref:reference.ref});
          const result = await request(`/api/report-references/validate?${query}`);
          const resolved = result.reference;
          if (resolved?.target_ref !== reference.ref || !resolved?.object?.canonical_name) throw new Error(t("researchDetail.invalidResponse"));
          openObject({kind:"product",ref:String(resolved.object.canonical_name),label}); return;
        }
        const kind = kinds[reference.kind];
        if (kind && openObject && (kind !== "productGroup" || reference.ref.startsWith("product-group:"))) {
          openObject({kind,ref:reference.ref,label,owner:binding?.data?.owner_ref || binding?.data?.owner_username,profileKey:binding?.data?.profile_key}); return;
        }
        setReferenceDetail({label,kind:reference.kind,target_ref:reference.ref,...(binding ? {binding} : {})});
      } catch (reason) {
        notify({code:"report.reference.failed",type:"error",message:t("loadFailed"),description:reason instanceof Error ? reason.message : String(reason)});
      } finally { pending.current = false; }
    })();
  };
  return <section className={`tr-report-reading-block tr-report-reading-${kind}`}>
    {title && !["chapter"].includes(kind) ? <h3>{title}</h3> : null}
    {body && kind !== "math" && component.display_kind !== "display_math" ? <Markdown value={body} onOpen={openReference} /> : null}
    {kind === "image" && assetURL ? <img className="tr-report-reading-image" loading="lazy" src={assetURL} alt={title || t("report.image")} />
      : kind === "image" ? <span>{t("report.imageUnavailable")}</span>
      : kind === "math" || component.display_kind === "display_math" ? <Formula latex={String(content?.latex || content?.formula || content || body)} />
      : kind === "table" ? <ReportTable value={content} onOpen={openReference} />
      : kind === "list" ? <ul>{entries.map((item,index) => <li key={index}><ReportCell value={item} onOpen={openReference} /></li>)}</ul>
      : kind === "code" || kind === "json" ? <pre>{typeof content === "string" ? content : JSON.stringify(content, null, 2)}</pre>
      : !body && content != null && kind !== "chapter" ? typeof content === "string" ? <Markdown value={content} onOpen={openReference} /> : <ResultView value={content} /> : null}
    {bindings.length ? <details className="tr-report-reading-references"><summary>{t("report.references", {count:bindings.length})}</summary>{bindings.map((binding,index) => {
      const ref = String(binding.target_ref || ""), kind = String(binding.kind || "").replaceAll("-","_"), label = String(binding.label || ref || kind);
      return <div key={String(binding.binding_id || index)}>{ref ? <button type="button" className="tr-table-link tr-object-reference" aria-label={t("objectReference.open",{name:label})} onClick={() => openReference({kind,ref},label)}>{label}</button> : <span>{label}</span>}</div>;
    })}</details> : null}
    {referenceDetail ? <DetailsPanel title={String(referenceDetail.label)} onClose={() => setReferenceDetail(null)}><ResultView value={referenceDetail} /></DetailsPanel> : null}
  </section>;
}

/** Read one authorized branch at a time, retaining only the selected chapter. */
export function ReportBranchReader({ target }: { target: ReportExportTarget }): React.ReactElement {
  const { t } = useTranslation();
  const indexURL = reportResourceURL(target,["index"]);
  const [index,setIndex] = useState<Row | null>(null), [chapterID,setChapterID] = useState(""), [chapter,setChapter] = useState<Row | null>(null);
  const [error,setError] = useState(""), [loading,setLoading] = useState(false), [indexRevision,setIndexRevision] = useState(0), [chapterRevision,setChapterRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setIndex(null); setChapter(null); setChapterID(""); setError("");
    if (!indexURL) {setError(t("report.exportMissingSource"));return () => controller.abort();}
    setLoading(true);
    void request(indexURL,{signal:controller.signal}).then(result => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(result.chapters)) throw new Error(t("researchDetail.invalidResponse"));
      setIndex(result); setChapterID(String(result.chapters[0]?.component_id || ""));
    }).catch(reason => {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [indexURL,indexRevision,t]);
  const chapterURL = chapterID ? reportResourceURL(target,["chapters",chapterID]) : null;
  useEffect(() => {
    const controller = new AbortController(); setChapter(null); if (!chapterURL) return () => controller.abort();
    setLoading(true); setError("");
    void request(chapterURL,{signal:controller.signal}).then(result => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(result.components)) throw new Error(t("researchDetail.invalidResponse"));
      setChapter(result);
    }).catch(reason => {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [chapterURL,chapterRevision,t]);
  const bindingsByComponent = useMemo(() => {
    const result = new Map<string, Row[]>();
    for (const binding of Array.isArray(chapter?.bindings) ? chapter.bindings : []) {
      const key = String(binding.component_id || "");
      const items = result.get(key);
      if (items) items.push(binding); else result.set(key, [binding]);
    }
    return result;
  }, [chapter]);
  return <section className="tr-report-reading" aria-label={t("report.read")}>
    {index?.chapters?.length ? <label className="tr-report-reading-choice"><span>{t("report.chapter")}</span><Select aria-label={t("report.chapter")} value={chapterID || undefined} onChange={setChapterID} options={index.chapters.map((item:Row) => ({value:String(item.component_id || ""),label:String(item.title || item.component_id || "")})).filter((item:Row) => item.value)} /></label> : null}
    {loading ? <Spin tip={t("loading")} /> : error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} action={<Button onClick={() => index ? setChapterRevision(value => value + 1) : setIndexRevision(value => value + 1)}>{t("retry")}</Button>} /> : chapter ? <article>{chapter.components.map((component:Row,index:number) => <ReportBlock key={String(component.component_id || index)} component={component} assets={chapter.assets || []} bindings={bindingsByComponent.get(String(component.component_id || "")) || []} resources={chapter.local_resources || []} target={target} />)}</article> : index ? <Empty description={t("empty")} /> : null}
  </section>;
}
