import React, { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Popover, Select, Spin } from "antd";
import { FontSizeOutlined } from "@ant-design/icons";
import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { reportResourceURL, type ReportExportTarget } from "../report-export.ts";
import { reportReference, type ReportReference } from "../report-references.ts";
import { REPORT_FONT_SIZES, readReportFont, writeReportFont } from "../report-reading-preference.ts";
import { reportJobReference, reportTree, validReportComponents, type ReportNode } from "../report-tree.ts";
import { useAuth } from "../auth.tsx";
import { referenceForField, type ObjectKind } from "../object-reference.ts";
import { downloadBlob } from "../download.ts";
import { notify } from "../notifications/core.ts";
import { Formula, loadFormulaRenderer, type FormulaRenderer } from "./formula.tsx";
import { reportMarkdown } from "../report-markdown.ts";
import { ObjectReference, ObjectReferenceContext } from "./object-reference.tsx";
import { ResultView } from "./result-view.tsx";
import { TRDataTable } from "./data-table.tsx";
import { DetailsPanel } from "./details-panel.tsx";
import { JobDetail } from "./job-detail.tsx";
import "./report-branch-reader.css";

type Row = Record<string, any>;
type ImageResolver = (href:string) => {url:string | null} | null;

function Markdown({ value, onOpen, resolveImage }: { value: string; onOpen: (reference:ReportReference,label:string) => void; resolveImage:ImageResolver }): React.ReactElement {
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
    },resolveImage), {
      FORBID_TAGS:["style","iframe","object","embed","form"], FORBID_ATTR:["style"],
    });
    return {html,formulas,links};
  }, [value,engine,resolveImage]);
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

function ReportCell({ value, field = "", parent = {}, onOpen, resolveImage }: { value:unknown; field?:string; parent?:Row; onOpen:(reference:ReportReference,label:string) => void; resolveImage:ImageResolver }): React.ReactElement {
  if (value && typeof value === "object") {
    const item = value as Row, target = String(item.target || item.href || item.url || item.reference || ""), label = String(item.label || item.title || item.text || item.filename || target);
    const reference = reportReference(target);
    if (reference) return <button type="button" className="tr-table-link tr-object-reference" onClick={() => onOpen(reference,label)}>{label}</button>;
    if (/^https?:\/\//i.test(target)) return <a href={target} target="_blank" rel="noopener noreferrer">{label}</a>;
    if (!target && typeof item.text === "string") return <ReportCell value={item.text} onOpen={onOpen} resolveImage={resolveImage} />;
    return <ResultView value={value} />;
  }
  const reference = referenceForField(field,value,parent);
  if (reference?.kind === "product") return <button type="button" className="tr-table-link tr-object-reference" onClick={() => onOpen({kind:"product",ref:reference.ref},reference.label || reference.ref)}>{reference.label || reference.ref}</button>;
  if (reference) return <ObjectReference value={reference} />;
  if (typeof value === "string" && /\[[^\]]+\]\(|\$|\\[([]/.test(value)) return <Markdown value={value} onOpen={onOpen} resolveImage={resolveImage} />;
  return <>{String(value ?? "—")}</>;
}

function ReportTable({ value, onOpen, resolveImage }: { value: unknown; onOpen:(reference:ReportReference,label:string) => void; resolveImage:ImageResolver }): React.ReactElement {
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
      return <ReportCell value={cell} field={String(typeof column === "object" ? column.key || "" : column)} parent={row && !Array.isArray(row) && typeof row === "object" ? row : {}} onOpen={onOpen} resolveImage={resolveImage} />;
    },
  }))} />;
}

function ReportBlock({ component, assets, bindings, resources, target, hideTitle = false }: { component: Row; assets: Row[]; bindings: Row[]; resources: Row[]; target: ReportExportTarget; hideTitle?:boolean }): React.ReactElement {
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
  const resolveImage = useCallback<ImageResolver>((href) => {
    const reference = reportReference(href);
    if (reference?.kind === "local_resource") {
      const resource = resources.find(item => item.resource_id === reference.ref);
      return {url:resource ? reportResourceURL(target,["local-resources",reference.ref],{inline:"1"}) : null};
    }
    const source = assets.find(item => [item.asset_id,item.asset_ref,item.external_ref,item.filename].some(value => value === href));
    if (source) {
      const id = String(source.asset_id || source.asset_ref || "");
      return {url:id ? reportResourceURL(target,["assets",id]) : null};
    }
    if (/^(?:https?:|data:|blob:)/i.test(href)) return null;
    return {url:null};
  },[assets,resources,target.publication_id,target.source_ref,target.source_kind,target.owner_ref,target.profile_ref,target.profile_id,target.report_workspace_id,target.branch_id]);
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
    {!hideTitle && title && !["chapter"].includes(kind) ? <h3>{title}</h3> : null}
    {body && kind !== "math" && component.display_kind !== "display_math" ? <Markdown value={body} onOpen={openReference} resolveImage={resolveImage} /> : null}
    {kind === "image" && assetURL ? <img className="tr-report-reading-image" loading="lazy" src={assetURL} alt={title || t("report.image")} />
      : kind === "image" ? <span>{t("report.imageUnavailable")}</span>
      : kind === "math" || component.display_kind === "display_math" ? <Formula latex={String(content?.latex || content?.formula || content || body)} />
      : kind === "table" ? <ReportTable value={content} onOpen={openReference} resolveImage={resolveImage} />
      : kind === "list" ? <ul>{entries.map((item,index) => <li key={index}><ReportCell value={item} onOpen={openReference} resolveImage={resolveImage} /></li>)}</ul>
      : kind === "code" || kind === "json" ? <pre>{typeof content === "string" ? content : JSON.stringify(content, null, 2)}</pre>
      : !body && content != null && kind !== "chapter" ? typeof content === "string" ? <Markdown value={content} onOpen={openReference} resolveImage={resolveImage} /> : <ResultView value={content} /> : null}
    {bindings.length ? <details className="tr-report-reading-references"><summary>{t("report.references", {count:bindings.length})}</summary>{bindings.map((binding,index) => {
      const ref = String(binding.target_ref || ""), kind = String(binding.kind || "").replaceAll("-","_"), label = String(binding.label || ref || kind);
      return <div key={String(binding.binding_id || index)}>{ref ? <button type="button" className="tr-table-link tr-object-reference" aria-label={t("objectReference.open",{name:label})} onClick={() => openReference({kind,ref},label)}>{label}</button> : <span>{label}</span>}</div>;
    })}</details> : null}
    {referenceDetail ? <DetailsPanel title={String(referenceDetail.label)} onClose={() => setReferenceDetail(null)}><ResultView value={referenceDetail} /></DetailsPanel> : null}
  </section>;
}

function ReportTreeNode({ node, assets, resources, bindings, target }: { node:ReportNode; assets:Row[]; resources:Row[]; bindings:Map<string,Row[]>; target:ReportExportTarget }): React.ReactElement {
  const { t } = useTranslation(), component = node.component, kind = String(component.kind || "");
  const [expanded,setExpanded] = useState(kind !== "special");
  const associated = bindings.get(String(component.component_id || "")) || [];
  const isResult = kind === "special" && component.display_kind === "test_result";
  const job = isResult ? reportJobReference(component,associated) : null;
  const descendants = node.children.map(child => <ReportTreeNode key={String(child.component.component_id)} node={child} assets={assets} resources={resources} bindings={bindings} target={target} />);
  const content = <ReportBlock component={component} assets={assets} bindings={associated} resources={resources} target={target} hideTitle={kind === "special" || kind === "section" || kind === "subsection"} />;
  if (kind === "chapter") return <>{content}{descendants}</>;
  if (["special","section","subsection"].includes(kind)) return <details className="tr-report-reading-section" open={expanded} onToggle={event => {if (event.target === event.currentTarget) setExpanded(event.currentTarget.open);}}>
    <summary>{String(component.title || component.display_kind || kind)}</summary>
    {expanded ? <div className="tr-report-reading-section-content">{isResult ? job ? <JobDetail job={job} readOnly /> : <Alert type="info" showIcon message={t("report.jobRoutingMissing")} /> : null}{content}{descendants}</div> : null}
  </details>;
  return <>{content}{descendants}</>;
}

/** Read one authorized branch at a time, retaining only the selected chapter. */
export function ReportBranchReader({ target, initialChapterID = "", onChapterChange }: { target: ReportExportTarget; initialChapterID?:string; onChapterChange?:(id:string) => void }): React.ReactElement {
  const { t } = useTranslation();
  const { session } = useAuth(), username = session?.username || "anonymous";
  const [fontSize,setFontSize] = useState(() => {try {return readReportFont(window.localStorage,username);} catch {return 16;}});
  useEffect(() => {try {writeReportFont(window.localStorage,username,fontSize);} catch { /* Storage may be unavailable. */ }}, [username,fontSize]);
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
      const chosen = result.chapters.some((item:Row) => item.component_id === initialChapterID) ? initialChapterID : String(result.chapters[0]?.component_id || "");
      setIndex(result); setChapterID(chosen);
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
      if (!validReportComponents(result.components)) throw new Error(t("researchDetail.invalidResponse"));
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
  const tree = useMemo(() => reportTree(Array.isArray(chapter?.components) ? chapter.components : []),[chapter]);
  return <section className="tr-report-reading" aria-label={t("report.read")} style={{"--tr-report-font-size":`${fontSize}px`} as React.CSSProperties}>
    {index?.chapters?.length ? <div className="tr-report-reading-toolbar"><label className="tr-report-reading-choice"><span>{t("report.chapter")}</span><Select aria-label={t("report.chapter")} value={chapterID || undefined} onChange={value => {setChapterID(value);onChapterChange?.(value);}} options={index.chapters.map((item:Row) => ({value:String(item.component_id || ""),label:String(item.title || item.component_id || "")})).filter((item:Row) => item.value)} /></label><Popover trigger="click" title={t("report.readingSettings")} content={<label className="tr-report-reading-font"><span>{t("report.fontSize")}</span><Select aria-label={t("report.fontSize")} value={fontSize} options={REPORT_FONT_SIZES.map(size => ({value:size,label:`${size} px`}))} onChange={setFontSize} /></label>}><Button type="text" icon={<FontSizeOutlined />} aria-label={t("report.readingSettings")} /></Popover></div> : null}
    {loading ? <Spin tip={t("loading")} /> : error ? <Alert type="error" showIcon message={t("loadFailed")} description={error} action={<Button onClick={() => index ? setChapterRevision(value => value + 1) : setIndexRevision(value => value + 1)}>{t("retry")}</Button>} /> : chapter ? <article>{tree.map(node => <ReportTreeNode key={String(node.component.component_id)} node={node} assets={chapter.assets || []} resources={chapter.local_resources || []} bindings={bindingsByComponent} target={target} />)}</article> : index ? <Empty description={t("empty")} /> : null}
  </section>;
}
