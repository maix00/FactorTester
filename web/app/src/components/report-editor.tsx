import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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

  const load = (): void => {
    Promise.all([
      fetch(`/api/research-reports/${encodeURIComponent(publicationID)}`, { credentials: "same-origin" }).then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))),
      fetch(`/api/research-reports/${encodeURIComponent(publicationID)}/projection`, { credentials: "same-origin" }).then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))),
    ]).then(([doc, proj]) => {
      setDocument(doc.document ?? doc);
      setProjection(proj.projection ?? proj);
    }).catch((error: Error) => notify({ code: "report.load", type: "error", message: t("loadFailed"), description: error.message }));
  };
  useEffect(load, [publicationID]);

  const apply = (operation: Record<string, unknown>): void => {
    if (!document?._rev) return;
    setBusy(true);
    fetch(`/api/research-reports/${encodeURIComponent(publicationID)}/operations`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_rev: document._rev, operation }),
    }).then(async (response) => {
      const value = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
      load();
    }).catch((error: Error) => notify({ code: "report.operation", type: "error", message: t("report.operationFailed"), description: error.message }))
      .finally(() => setBusy(false));
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
    if (operations.length) { apply({ op: "batch", operations }); setSelected([]); }
  };

  return (
    <div className="tr-report-editor">
      <div className="tr-report-add">
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t("report.paragraphTitle")} />
        <textarea value={body} onChange={(event) => setBody(event.target.value)} placeholder={t("report.paragraphBody")} />
        <button type="button" className="tr-toolbar-button" disabled={busy || !firstChapter || !body.trim()} onClick={() => {
          apply({ op: "insert_component", chapter_id: firstChapter, component: { kind: "paragraph", title, body } });
          setTitle(""); setBody("");
        }}>{t("report.addParagraph")}</button>
      </div>
      {selected.length ? <button type="button" className="tr-toolbar-button" disabled={busy} onClick={batchDelete}>{t("report.removeSelected", { count: selected.length })}</button> : null}
      {chapters.map((chapter) => {
        const chapterID = String(chapter.chapter_id ?? chapter.component_id ?? "");
        return (
          <section key={chapterID} className="tr-report-chapter">
            <h3>{chapter.title || chapterID}</h3>
            {(chapter.components ?? []).map((component, index, list) => (
              <div className="tr-report-component" key={String(component.component_id)}>
                <div>
                  {component.component_id ? <input type="checkbox" checked={selected.includes(component.component_id)} onChange={() => setSelected((current) => current.includes(component.component_id!) ? current.filter((value) => value !== component.component_id) : [...current, component.component_id!])} /> : null}
                  <b>{component.title || component.kind || component.component_id}</b>{component.body ? <p>{component.body}</p> : null}
                </div>
                <div className="tr-report-component-actions">
                  {component.component_id && index > 0 ? (
                    <button type="button" disabled={busy} onClick={() => apply({
                      op: "move_component", chapter_id: chapterID, component_id: component.component_id,
                      parent_id: component.parent_id || "root",
                      after_component_id: index > 1 ? list[index - 2]?.component_id || "" : "",
                    })}>↑</button>
                  ) : null}
                  {component.component_id && index < list.length - 1 ? (
                    <button type="button" disabled={busy} onClick={() => apply({
                      op: "move_component", chapter_id: chapterID, component_id: component.component_id,
                      parent_id: component.parent_id || "root",
                      after_component_id: list[index + 1]?.component_id || "",
                    })}>↓</button>
                  ) : null}
                  {component.component_id ? <button type="button" disabled={busy} onClick={() => apply({
                    op: "remove_component", chapter_id: chapterID, component_id: component.component_id,
                  })}>{t("report.remove")}</button> : null}
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
