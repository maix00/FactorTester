import React, { useEffect, useRef, useState } from "react";
import { Button, Form, Input } from "antd";
import { ArrowUpOutlined, ArrowDownOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { notify } from "../notifications/core.ts";

type Component = { component_id?: string; kind?: string; title?: string; body?: string; parent_id?: string };
type Chapter = { chapter_id?: string; component_id?: string; title?: string; components?: Component[] };
type Projection = { chapters?: Chapter[] };

export function ReportEditor({ publicationID }: { publicationID: string }): React.ReactElement {
  const { t } = useTranslation();
  const [document, setDocument] = useState<Record<string, unknown> | null>(null);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const operationPending = useRef(false);
  const operationRequest = useRef<AbortController | null>(null);
  const activePublication = useRef(publicationID); activePublication.current = publicationID;
  const loadRevision = useRef(0);
  const [attachments, setAttachments] = useState<Record<string, unknown>[]>([]);

  const load = async (signal?: AbortSignal): Promise<void> => {
    const revision = ++loadRevision.current;
    return Promise.all([
      request(`/api/research-reports/${encodeURIComponent(publicationID)}`, { signal }),
      request(`/api/research-reports/${encodeURIComponent(publicationID)}/projection`, { signal }),
      request(`/api/research-reports/${encodeURIComponent(publicationID)}/attachments`, { signal }),
    ]).then(([doc, proj, files]) => {
      if (signal?.aborted || revision !== loadRevision.current || activePublication.current !== publicationID) return;
      setDocument(doc.document ?? doc);
      setProjection(proj.projection ?? proj);
      setAttachments(files.attachments ?? files.items ?? []);
    }).catch((error: Error) => { if (!signal?.aborted && revision === loadRevision.current && activePublication.current === publicationID) notify({ code: "report.load", type: "error", message: t("loadFailed"), description: error.message }); });
  };
  useEffect(() => { const controller = new AbortController(); setDocument(null); setProjection(null); setAttachments([]); setSelected([]); setTitle(""); setBody(""); setBusy(false); operationPending.current = false; operationRequest.current = null; void load(controller.signal); return () => { controller.abort(); operationRequest.current?.abort(); ++loadRevision.current; }; }, [publicationID]);

  const apply = async (operation: Record<string, unknown>): Promise<boolean> => {
    if (!document?._rev || operationPending.current) return false;
    operationPending.current = true; setBusy(true);
    const controller = new AbortController(); operationRequest.current = controller;
    return request(`/api/research-reports/${encodeURIComponent(publicationID)}/operations`, {
      method: "POST", credentials: "same-origin", signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_rev: document._rev, operation }),
    }).then(async () => {
      if (activePublication.current !== publicationID) return false;
      await load(controller.signal); return !controller.signal.aborted;
    }).catch((error: Error) => { if (!controller.signal.aborted && activePublication.current === publicationID) notify({ code: "report.operation", type: "error", message: t("report.operationFailed"), description: error.message }); return false; })
      .finally(() => { if (operationRequest.current === controller) { operationRequest.current = null; operationPending.current = false; if (activePublication.current === publicationID) setBusy(false); } });
  };

  const chapters = projection?.chapters ?? [];
  const firstChapter = chapters[0]?.chapter_id ?? chapters[0]?.component_id ?? "";
  const batchDelete = (): void => {
    const operations = chapters.flatMap((chapter) => {
      const chapterID = String(chapter.chapter_id ?? chapter.component_id ?? "");
      return (chapter.components ?? [])
        .filter((component) => component.component_id && selected.includes(component.component_id))
        .map((component) => ({
          op: "remove_component", chapter_id: chapterID, component_id: component.component_id,
        }));
    });
    if (operations.length) { void apply({ op: "batch", operations }).then(saved => { if (saved) setSelected([]); }); }
  };

  return (
    <div className="tr-report-editor">
      <Form layout="vertical" className="tr-report-add">
        <Form.Item label={t("report.paragraphTitle")}><Input aria-label={t("report.paragraphTitle")} disabled={busy} value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t("report.paragraphTitle")} /></Form.Item>
        <Form.Item label={t("report.paragraphBody")}><Input.TextArea aria-label={t("report.paragraphBody")} disabled={busy} autoSize={{ minRows: 4, maxRows: 12 }} value={body} onChange={(event) => setBody(event.target.value)} placeholder={t("report.paragraphBody")} /></Form.Item>
        <Button type="primary" loading={busy} disabled={busy || !firstChapter || !body.trim()} onClick={() => {
          void apply({ op: "insert_component", chapter_id: firstChapter, component: { kind: "paragraph", title, body } }).then(saved => { if (saved) { setTitle(""); setBody(""); } });
        }}>{t("report.addParagraph")}</Button>
      </Form>
      {selected.length ? <Button danger disabled={busy} onClick={batchDelete}>{t("report.removeSelected", { count: selected.length })}</Button> : null}
      {attachments.length ? (
        <section className="tr-report-chapter">
          <h3>{t("report.attachments")}</h3>
          {attachments.map((file, index) => {
            const name = String(file.path ?? file.name ?? index);
            return <div className="tr-report-component" key={name}><span>{String(file.path ?? file.name ?? name)}</span><a href={`/api/research-reports/${encodeURIComponent(publicationID)}/attachments/${encodeURIComponent(name)}`} target="_blank" rel="noreferrer">{t("report.open")}</a></div>;
          })}
        </section>
      ) : null}
      {chapters.map((chapter, chapterIndex) => {
        const chapterID = String(chapter.chapter_id ?? chapter.component_id ?? "");
        return (
          <section key={chapterID} className="tr-report-chapter">
            <h3>
              {chapter.title || chapterID}
              <span className="tr-report-chapter-actions">
                {chapterIndex > 0 ? <Button size="small" disabled={busy} onClick={() => apply({ op: "move_chapter", chapter_id: chapterID, after_chapter_id: chapterIndex > 1 ? String(chapters[chapterIndex - 2].chapter_id ?? chapters[chapterIndex - 2].component_id ?? "") : null })} aria-label={t("report.moveUp")} icon={<ArrowUpOutlined />} /> : null}
                {chapterIndex < chapters.length - 1 ? <Button size="small" disabled={busy} onClick={() => apply({ op: "move_chapter", chapter_id: chapterID, after_chapter_id: chapters[chapterIndex + 1].chapter_id ?? chapters[chapterIndex + 1].component_id ?? "" })} aria-label={t("report.moveDown")} icon={<ArrowDownOutlined />} /> : null}
              </span>
            </h3>
            {(chapter.components ?? []).map((component, index, list) => (
              <div className="tr-report-component" key={String(component.component_id)}>
                <div>
                  {component.component_id ? <input type="checkbox" checked={selected.includes(component.component_id)} onChange={() => setSelected((current) => current.includes(component.component_id!) ? current.filter((value) => value !== component.component_id) : [...current, component.component_id!])} /> : null}
                  <b>{component.title || component.kind || component.component_id}</b>{component.body ? <p>{component.body}</p> : null}
                </div>
                <div className="tr-report-component-actions">
                  {component.component_id && index > 0 ? (
                    <Button size="small" disabled={busy} onClick={() => apply({
                      op: "move_component", chapter_id: chapterID, component_id: component.component_id,
                      parent_id: component.parent_id || "root",
                      after_component_id: index > 1 ? list[index - 2]?.component_id || "" : "",
                    })} aria-label={t("report.moveUp")} icon={<ArrowUpOutlined />} />
                  ) : null}
                  {component.component_id && index < list.length - 1 ? (
                    <Button size="small" disabled={busy} onClick={() => apply({
                      op: "move_component", chapter_id: chapterID, component_id: component.component_id,
                      parent_id: component.parent_id || "root",
                      after_component_id: list[index + 1]?.component_id || "",
                    })} aria-label={t("report.moveDown")} icon={<ArrowDownOutlined />} />
                  ) : null}
                  {component.component_id ? <Button size="small" disabled={busy} onClick={() => apply({
                    op: "remove_component", chapter_id: chapterID, component_id: component.component_id,
                  })}>{t("report.remove")}</Button> : null}
                </div>
              </div>
            ))}
          </section>
        );
      })}
      {chapters.length === 0 ? <p>{t("empty")}</p> : null}
    </div>
  );
}
