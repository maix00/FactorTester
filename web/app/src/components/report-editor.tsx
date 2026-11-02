import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Checkbox, Form, Input, Popconfirm, Select, Spin } from "antd";
import { ArrowUpOutlined, ArrowDownOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { downloadBlob } from "../download.ts";
import { notify } from "../notifications/core.ts";
import { insertParagraph, moveReportComponent, removeReportComponents, type ReportChapter, type ReportComponent } from "../report-edit-model.ts";

type ChapterSummary = { chapter_id?: string; title?: string };
type DocumentValue = { _rev?: string; projection_hash?: string };
type Attachment = { path?: string; name?: string };

/** Edit only the current chapter, using its real parent and sibling identities. */
export function ReportEditor({ publicationID, onUpdated, requester = request, appendOnly = false }: { publicationID: string; onUpdated?: () => void; requester?:typeof request; appendOnly?:boolean }): React.ReactElement {
  const { t } = useTranslation();
  const [document,setDocument] = useState<DocumentValue | null>(null), [canWrite,setCanWrite] = useState<boolean | null>(null);
  const [chapters,setChapters] = useState<ChapterSummary[]>([]), [chapterID,setChapterID] = useState(""), [chapter,setChapter] = useState<ReportChapter | null>(null);
  const [attachments,setAttachments] = useState<Attachment[]>([]), [selected,setSelected] = useState<string[]>([]);
  const [attachmentError,setAttachmentError] = useState(false);
  const [title,setTitle] = useState(""), [body,setBody] = useState(""), [chapterTitle,setChapterTitle] = useState("");
  const [editing,setEditing] = useState(false), [busy,setBusy] = useState(false), [chapterLoading,setChapterLoading] = useState(false);
  const [requestedPublication,setRequestedPublication] = useState("");
  const enabled = requestedPublication === publicationID && !!publicationID;
  const [loadError,setLoadError] = useState(""), [chapterError,setChapterError] = useState(""), [needsReview,setNeedsReview] = useState(false), [chapterRevision,setChapterRevision] = useState(0);
  const operationPending = useRef(false), operationRequest = useRef<AbortController | null>(null), loadRevision = useRef(0), attachmentRevision = useRef(0);
  const activePublication = useRef(publicationID); activePublication.current = publicationID;
  const base = `/api/research-reports/${encodeURIComponent(publicationID)}`;

  const load = async (signal?:AbortSignal, notifyFailure = false): Promise<boolean> => {
    const revision = ++loadRevision.current;
    try {
      const [doc,agent] = await Promise.all([requester(base,{signal}),requester(`${base}/agent`,{signal})]);
      if (signal?.aborted || revision !== loadRevision.current || activePublication.current !== publicationID) return false;
      if (!doc.document?._rev || !Array.isArray(agent.manifest?.chapters)) throw new Error(t("researchDetail.invalidResponse"));
      const next = agent.manifest.chapters as ChapterSummary[];
      setDocument(doc.document); setCanWrite(typeof doc.access?.can_write === "boolean" ? doc.access.can_write : null);
      setChapters(next); setChapterID(previous => next.some(item => item.chapter_id === previous) ? previous : String(next[0]?.chapter_id || ""));
      setLoadError(""); return true;
    } catch (reason) {
      if (!signal?.aborted && revision === loadRevision.current && activePublication.current === publicationID) {
        const description = reason instanceof Error ? reason.message : String(reason);
        setLoadError(description);
        if (notifyFailure) notify({code:"report.editor.load.failed",type:"error",message:`${t("report.editContents")} · ${t("loadFailed")}`,description});
      }
      return false;
    }
  };
  useEffect(() => {
    const controller = new AbortController(); setDocument(null); setCanWrite(null); setChapters([]); setChapter(null); setChapterID(""); setLoadError(""); setNeedsReview(false); setSelected([]); setEditing(enabled); setTitle(""); setBody(""); setChapterTitle("");
    if (enabled) void load(controller.signal, true);
    return () => { controller.abort(); operationRequest.current?.abort(); ++loadRevision.current; };
  }, [publicationID,enabled]);
  const loadAttachments = async (signal?:AbortSignal, notifyFailure = false): Promise<void> => {
    const revision = ++attachmentRevision.current;
    try {
      const value = await requester(`${base}/attachments`,{signal});
      if (signal?.aborted || revision !== attachmentRevision.current || activePublication.current !== publicationID) return;
      if (!Array.isArray(value.attachments)) throw new Error(t("researchDetail.invalidResponse"));
      setAttachments(value.attachments); setAttachmentError(false);
    } catch (reason) {
      if (!signal?.aborted && revision === attachmentRevision.current && activePublication.current === publicationID) {
        setAttachmentError(true);
        if (notifyFailure) notify({code:"report.attachments.load.failed",type:"error",message:`${t("report.attachments")} · ${t("loadFailed")}`,description:reason instanceof Error ? reason.message : String(reason)});
      }
    }
  };
  useEffect(() => {
    const controller = new AbortController(); setAttachments([]); setAttachmentError(false);
    void loadAttachments(controller.signal);
    return () => {controller.abort(); ++attachmentRevision.current;};
  }, [publicationID]);
  useEffect(() => {
    const controller = new AbortController(); setChapter(null); setChapterError("");
    if (!chapterID || !editing) { setChapterLoading(false); return () => controller.abort(); }
    setChapterLoading(true);
    void requester(`${base}/chapters/${encodeURIComponent(chapterID)}`,{signal:controller.signal}).then(value => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(value.chapter?.components)) throw new Error(t("researchDetail.invalidResponse"));
      setChapter({...value.chapter,chapter_id:chapterID});
    }).catch(reason => {if (!controller.signal.aborted) setChapterError(reason instanceof Error ? reason.message : String(reason));})
      .finally(() => {if (!controller.signal.aborted) setChapterLoading(false);});
    return () => controller.abort();
  }, [publicationID,chapterID,editing,chapterRevision,t]);
  useEffect(() => {setSelected([]);}, [chapterID]);

  const apply = async (operation:Record<string,unknown>): Promise<boolean> => {
    if (!document?._rev || canWrite !== true || loadError || needsReview || operationPending.current) return false;
    operationPending.current = true; setBusy(true);
    const controller = new AbortController(); operationRequest.current = controller;
    try {
      await requester(`${base}/operations`,{method:"POST",signal:controller.signal,body:JSON.stringify({base_rev:document._rev,operation})});
      if (activePublication.current !== publicationID) return false;
      const refreshed = await load(controller.signal);
      if (!refreshed && !controller.signal.aborted) setNeedsReview(true);
      if (refreshed) {setChapterRevision(value => value + 1);void loadAttachments();onUpdated?.();notify({code:"report.operation.success",type:"success",message:t("operations.saved")});}
      return refreshed;
    } catch (reason) {
      if (!controller.signal.aborted && activePublication.current === publicationID) {
        const error = reason as Error & {status?:number};
        const description = error.status === 409 ? t("report.revisionConflict") : error.status === 403 ? t("report.noWrite") : error.status === 503 ? t("report.writeUnknown") : error.message;
        if (!error.status || error.status === 409) {setLoadError(description);setNeedsReview(true);}
        if (error.status === 403) setCanWrite(false);
        if (error.status === 503) setCanWrite(null);
        notify({code:"report.operation.failed",type:"error",message:t("report.operationFailed"),description});
      }
      return false;
    } finally {
      if (operationRequest.current === controller) {operationRequest.current = null;operationPending.current = false;if (activePublication.current === publicationID) setBusy(false);}
    }
  };
  const attachment = async (file:Attachment): Promise<void> => {
    if (!file.name) return;
    try {
      const response = await fetch(`${base}/attachments/${encodeURIComponent(file.name)}`,{credentials:"same-origin",redirect:"error"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      downloadBlob(await response.blob(),file.path || file.name);
    } catch (reason) {notify({code:"report.attachment.failed",type:"error",message:t("loadFailed"),description:reason instanceof Error ? reason.message : String(reason)});}
  };
  const retryLoad = (): void => {
    if (editing && chapterID) setChapterLoading(true);
    void load(undefined,!needsReview).then(refreshed => {
      if (refreshed) {setChapterRevision(value => value + 1);void loadAttachments();onUpdated?.();}
      else setChapterLoading(false);
    });
  };
  const nextID = (prefix:string): string => `${prefix}-${crypto.randomUUID().replaceAll("-","").slice(0,16)}`;
  const locked = busy || !!loadError || needsReview || chapterLoading || !!chapterError;
  const components = (chapter?.components || []).filter(item => item.kind !== "chapter" && item.component_id);
  const componentsByID = useMemo(() => new Map((chapter?.components || []).map(item => [item.component_id,item])),[chapter]);
  const addParagraph = (): void => {
    if (!chapter) return;
    const operation = insertParagraph(chapter,nextID("component"),title.trim(),body);
    if (operation) void apply(operation).then(saved => {if (saved) {setTitle("");setBody("");}});
  };
  const removeSelected = (): void => {
    if (!chapter) return;
    const operations = removeReportComponents(chapter,selected);
    if (operations.length) void apply({op:"batch",operations}).then(saved => {if (saved) setSelected([]);});
  };
  const componentDepth = (component:ReportComponent): number => {
    const seen = new Set<string>();
    let parent = component.parent_id, depth = 0;
    while (parent && parent !== chapterID && !seen.has(parent) && depth < 5) {seen.add(parent);depth++;parent = componentsByID.get(parent)?.parent_id;}
    return depth;
  };
  return <section className="tr-report-editor">
    {!enabled ? <Button onClick={() => setRequestedPublication(publicationID)}>{t("report.editContents")}</Button> : null}
    {enabled && loadError && needsReview ? <Alert type="error" showIcon message={t("report.reloadRequired")} description={loadError} action={<Button onClick={retryLoad}>{t("retry")}</Button>} /> : null}
    {enabled && loadError && !needsReview ? <Button onClick={retryLoad}>{t("retry")}</Button> : null}
    {enabled && !document && !loadError ? <Spin tip={t("loading")} /> : null}
    {enabled && needsReview && !loadError ? <Alert type="warning" showIcon message={t("report.reviewAfterReload")} action={<Button disabled={chapterLoading || !!chapterError} onClick={() => setNeedsReview(false)}>{t("report.reviewed")}</Button>} /> : null}
    {enabled && document && canWrite === null ? <Alert type="warning" showIcon message={t("report.writeUnknown")} action={<Button onClick={() => void load()}>{t("retry")}</Button>} /> : null}
    {enabled && document && canWrite === false ? <p>{t("report.noWrite")}</p> : null}
    {enabled && document && canWrite === true ? <Button onClick={() => setEditing(value => !value)}>{editing ? t("configuration.cancel") : t("report.editContents")}</Button> : null}
    {enabled && editing && canWrite === true ? <>
      {document?.projection_hash ? <Form layout="vertical" className="tr-report-add" onFinish={() => {
        if (!chapterTitle.trim()) return;
        void apply({op:"insert_chapter",chapter_id:nextID("chapter"),title:chapterTitle.trim(),after_chapter_id:chapters.at(-1)?.chapter_id || null}).then(saved => {if (saved) setChapterTitle("");});
      }}><Form.Item label={t("report.chapterTitle")}><Input aria-label={t("report.chapterTitle")} value={chapterTitle} onChange={event => setChapterTitle(event.target.value)} /></Form.Item><Button htmlType="submit" disabled={locked || !chapterTitle.trim()}>{t("report.addChapter")}</Button></Form> : null}
      <Form layout="vertical" className="tr-report-add">
        <Form.Item label={t("report.targetChapter")}><Select aria-label={t("report.targetChapter")} disabled={busy || !chapters.length} value={chapterID || undefined} options={chapters.map(item => ({value:String(item.chapter_id || ""),label:item.title || String(item.chapter_id || "")})).filter(item => item.value)} onChange={setChapterID} /></Form.Item>
        {chapterLoading ? <Spin tip={t("loading")} /> : chapterError ? <Alert type="error" showIcon message={t("loadFailed")} description={chapterError} action={<Button onClick={() => setChapterRevision(value => value + 1)}>{t("retry")}</Button>} /> : null}
        <Form.Item label={t("report.paragraphTitle")}><Input aria-label={t("report.paragraphTitle")} disabled={locked} value={title} onChange={event => setTitle(event.target.value)} /></Form.Item>
        <Form.Item label={t("report.paragraphBody")}><Input.TextArea aria-label={t("report.paragraphBody")} disabled={locked} autoSize={{minRows:4,maxRows:12}} value={body} onChange={event => setBody(event.target.value)} /></Form.Item>
        <Button type="primary" loading={busy} disabled={locked || !chapter || !body.trim()} onClick={addParagraph}>{t("report.addParagraph")}</Button>
      </Form>
      {selected.length ? <Popconfirm title={t("report.removeComponentsConfirm")} onConfirm={removeSelected}><Button danger disabled={locked}>{t("report.removeSelected",{count:selected.length})}</Button></Popconfirm> : null}
      <div className="tr-report-chapter">
        {chapters.map((item,index) => <div className="tr-report-component" key={item.chapter_id}><span>{item.title || item.chapter_id}</span><span className="tr-report-chapter-actions">
          {!appendOnly && index > 0 ? <Button size="small" disabled={locked} onClick={() => void apply({op:"move_chapter",chapter_id:item.chapter_id,after_chapter_id:index > 1 ? chapters[index-2]?.chapter_id : null})} aria-label={t("report.moveUp")} icon={<ArrowUpOutlined />} /> : null}
          {!appendOnly && index < chapters.length - 1 ? <Button size="small" disabled={locked} onClick={() => void apply({op:"move_chapter",chapter_id:item.chapter_id,after_chapter_id:chapters[index+1]?.chapter_id})} aria-label={t("report.moveDown")} icon={<ArrowDownOutlined />} /> : null}
          {!appendOnly && document?.projection_hash ? <Popconfirm title={t("report.removeChapterConfirm")} onConfirm={() => void apply({op:"remove_chapter",chapter_id:item.chapter_id})}><Button size="small" danger disabled={locked}>{t("report.remove")}</Button></Popconfirm> : null}
        </span></div>)}
      </div>
      {components.length ? <section className="tr-report-chapter"><h3>{t("report.components")}</h3>{components.map(item => {
        const id = String(item.component_id), label = item.title || item.kind || id;
        const up = chapter && moveReportComponent(chapter,id,"up"), down = chapter && moveReportComponent(chapter,id,"down");
        return <div className="tr-report-component" key={id} style={{marginInlineStart:componentDepth(item)*12}}><div>{!appendOnly ? <Checkbox checked={selected.includes(id)} aria-label={t("report.selectComponent",{name:label})} onChange={event => {
          if (event.target.checked && selected.length >= 100) {notify({code:"report.selection-limit",type:"warning",message:t("report.selectionLimit")});return;}
          setSelected(current => event.target.checked ? [...current,id] : current.filter(value => value !== id));
        }} />:null}<b>{label}</b>{item.body ? <p>{item.body}</p> : null}</div><div className="tr-report-component-actions">
          {!appendOnly && up ? <Button size="small" disabled={locked} onClick={() => void apply(up)} aria-label={t("report.moveUp")} icon={<ArrowUpOutlined />} /> : null}
          {!appendOnly && down ? <Button size="small" disabled={locked} onClick={() => void apply(down)} aria-label={t("report.moveDown")} icon={<ArrowDownOutlined />} /> : null}
          {!appendOnly ? <Popconfirm title={t("report.removeComponentConfirm")} onConfirm={() => void apply({op:"remove_component",chapter_id:chapterID,component_id:id,include_children:true})}><Button size="small" danger disabled={locked}>{t("report.remove")}</Button></Popconfirm> : null}
        </div></div>;
      })}</section> : null}
    </> : null}
    {attachmentError ? <Button onClick={() => void loadAttachments(undefined,true)}>{t("report.attachments")}</Button> : null}
    {attachments.length ? <section className="tr-report-chapter"><h3>{t("report.attachments")}</h3>{attachments.map((file,index) => <div className="tr-report-component" key={file.path || file.name || index}><span>{file.path || file.name}</span>{file.name ? <Button type="link" onClick={() => void attachment(file)}>{t("jobs.download")}</Button> : null}</div>)}</section> : null}
  </section>;
}
