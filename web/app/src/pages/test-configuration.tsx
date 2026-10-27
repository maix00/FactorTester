import React, { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Modal, Pagination, Segmented, Select, Tag } from "antd";
import Form from "@rjsf/antd";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema } from "@rjsf/utils";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { CodeView } from "../configuration/code-view.tsx";
import { acknowledgeSave, createDraft, fieldSchema, parseDraft, readPath, writePath,
         type Draft, type JSONObject, type Path } from "../configuration/draft.ts";
import "../configuration/editor.css";

interface Workspace { workspace_id: string; title: string }
interface Field { path: Path; key: string; analysis: string; group: string; title: string; description: string; value: unknown }
interface Contract { schema: JSONObject; catalog: Field[] }
interface Configuration { payload: JSONObject; revision: number }

async function request(url: string, options: RequestInit = {}): Promise<any> {
  const response = await fetch(url, { ...options, credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...options.headers } });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(value.error || `HTTP ${response.status}`), { status: response.status });
  return value;
}

const NO_DEFAULTS = { emptyObjectFields: "skipDefaults", arrayMinItems: { populate: "never" },
  allOf: "skipDefaults", constAsDefaults: "never", requiredBooleanDefault: "skip" } as const;

export function TestConfigurationPage(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState(() => new URLSearchParams(location.search).get("workspace_id") || "");
  const [contract, setContract] = useState<Contract | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [mode, setMode] = useState("form");
  const [query, setQuery] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<Path | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [discard, setDiscard] = useState<{ workspace?: string; reload?: boolean } | null>(null);
  const [reload, setReload] = useState(0);
  const activeWorkspace = useRef(workspace);
  activeWorkspace.current = workspace;
  const parsed = useMemo(() => parseDraft(draft?.text ?? "{}"), [draft?.text]);
  const deferredText = useDeferredValue(draft?.text ?? "{}");
  const validationErrors = useMemo(() => {
    const result = parseDraft(deferredText);
    return result.value && contract ? validator.validateFormData(result.value, contract.schema as RJSFSchema).errors : [];
  }, [deferredText, contract]);
  const dirty = !!draft && draft.text !== draft.savedText;

  useEffect(() => {
    const controller = new AbortController();
    request(`/api/test-authoring/configuration-schema?locale=${encodeURIComponent(i18n.language)}`, { signal: controller.signal })
      .then(setContract).catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [i18n.language]);

  useEffect(() => {
    const controller = new AbortController();
    request("/api/test-authoring/workspace-summaries", { signal: controller.signal })
      .then((value) => setWorkspaces(value.workspaces ?? []))
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!workspace) { setDraft(null); return; }
    const controller = new AbortController();
    setLoading(true); setError(""); setConflict(false); setDraft(null); setSelection(null);
    request(`/api/test-authoring/workspaces/${encodeURIComponent(workspace)}/configuration`, { signal: controller.signal })
      .then((value: { configuration: Configuration }) => {
        if (!controller.signal.aborted) setDraft(createDraft(value.configuration.payload, value.configuration.revision));
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspace, reload]);

  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent): void => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);

  const catalog = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (contract?.catalog ?? []).filter((field) => (!analysis || field.analysis === analysis)
      && (!needle || `${field.title} ${field.key} ${field.description}`.toLowerCase().includes(needle)));
  }, [contract, query, analysis]);

  const change = (text: string): void => setDraft((current) => current ? { ...current, text, source: "json" } : current);
  const edit = (path: Path, value: unknown): void => {
    if (!draft) return;
    try {
      const text = writePath(draft.text, path, value);
      setDraft((current) => current ? { ...current, text, source: "form" } : current);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  };
  const create = async (): Promise<void> => {
    setLoading(true);
    try {
      const value = await request("/api/test-authoring/workspaces", { method: "POST",
        body: JSON.stringify({ title: t("configuration.newTitle"), factors: [] }) });
      const row = value.workspace as Workspace;
      setWorkspaces((current) => [row, ...current]);
      setWorkspace(row.workspace_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  };
  const save = async (): Promise<void> => {
    if (!draft || !contract || !parsed.value || saving) return;
    const errors = validator.validateFormData(parsed.value, contract.schema as RJSFSchema).errors;
    if (errors.length) { setError(t("configuration.fixErrors")); return; }
    const submitted = draft.text;
    const savingWorkspace = workspace;
    setSaving(true); setError("");
    try {
      const result = await request(`/api/test-authoring/workspaces/${encodeURIComponent(workspace)}/configuration`, {
        method: "PUT", body: JSON.stringify({ expected_revision: draft.revision, payload: parsed.value }),
      }) as { configuration: Configuration };
      if (activeWorkspace.current !== savingWorkspace) return;
      setDraft((current) => current ? acknowledgeSave(current, submitted, result.configuration.payload, result.configuration.revision) : current);
      setConflict(false);
      notify({ code: "configuration.saved", type: "success", message: t("configuration.saved") });
    } catch (reason) {
      if (activeWorkspace.current !== savingWorkspace) return;
      if ((reason as { status?: number }).status === 409) setConflict(true);
      else setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setSaving(false); }
  };

  const selectedSchema = contract && selection ? fieldSchema(contract.schema, selection) : null;
  const selectedValue = selection && parsed.value ? readPath(parsed.value, selection) : undefined;
  const currentFields = (contract?.catalog ?? []).filter((field) => parsed.value && readPath(parsed.value, field.path) !== undefined);
  return <section className="tr-config-page" aria-label={t("configuration.title")}>
    <header className="tr-config-header"><div><h1>{t("configuration.title")}</h1><p>{t("configuration.hint")}</p></div>
      <Tag color={dirty ? "gold" : "default"}>{dirty ? t("configuration.unsaved") : t("configuration.savedState")}</Tag>
    </header>
    <div className="tr-config-toolbar">
      <Select aria-label={t("configuration.workspace")} placeholder={t("configuration.workspace")} value={workspace || undefined}
        options={workspaces.map((row) => ({ value: row.workspace_id, label: row.title || row.workspace_id }))}
        onChange={(value: string) => dirty ? setDiscard({ workspace: value }) : setWorkspace(value)} disabled={saving} />
      <Button onClick={() => dirty ? setDiscard({ workspace: "" }) : void create()} disabled={saving} loading={loading}>{t("configuration.create")}</Button>
      <Segmented value={mode} options={[{ label: t("configuration.fields"), value: "form" }, { label: t("configuration.json"), value: "json" }]}
        onChange={(value) => setMode(String(value))} />
      <Button onClick={() => dirty ? setDiscard({ reload: true }) : setReload((value) => value + 1)} disabled={!workspace || saving}>{t("configuration.reload")}</Button>
      <Button type="primary" loading={saving} disabled={!draft || loading || !dirty || !!parsed.error || conflict || !contract} onClick={() => void save()}>{t("configuration.save")}</Button>
    </div>
    {conflict ? <Alert type="warning" showIcon message={t("configuration.conflict")} /> : null}
    {error ? <Alert type="error" showIcon message={error} closable onClose={() => setError("")} /> : null}
    {loading ? <p role="status">{t("configuration.loading")}</p> : null}
    {!draft ? !loading ? <Empty description={t("configuration.chooseWorkspace")} /> : null : contract ? <div className="tr-config-layout">
      <aside className="tr-config-sidebar" aria-label={t("configuration.addFields")}>
        <h2>{t("configuration.addFields")}</h2>
        <Input.Search aria-label={t("configuration.search")} placeholder={t("configuration.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} allowClear />
        <Select aria-label={t("configuration.analysis")} value={analysis} onChange={(value) => { setAnalysis(value); setPage(1); }}
          options={[{ value: "", label: t("configuration.allAnalyses") }, ...[...new Set((contract.catalog ?? []).map((field) => field.analysis))].map((value) => ({ value, label: value }))]} />
        <div className="tr-config-catalog">{catalog.slice((page - 1) * 12, page * 12).map((field) => {
          const exists = parsed.value && readPath(parsed.value, field.path) !== undefined;
          return <button type="button" key={field.path.join(".")} className={selection?.join(".") === field.path.join(".") ? "is-selected" : ""}
            disabled={!!parsed.error} title={field.description || field.key} onClick={() => {
              if (!exists) edit(field.path, field.value);
              setSelection(field.path); setMode("form");
            }}><span className="tr-config-field-title">{exists ? "✓" : "+"} {field.title}</span><small>{field.analysis} · {field.key}</small></button>;
        })}</div>
        <Pagination simple size="small" current={page} total={catalog.length} pageSize={12} onChange={setPage} hideOnSinglePage />
      </aside>
      <main className="tr-config-content">
        {mode === "json" ? <CodeView text={draft.text} schema={contract.schema} onChange={change} applyExternal={draft.source !== "json"} /> : parsed.error ?
          <Alert type="error" showIcon message={t("configuration.invalidJSON")} description={parsed.error}
            action={<Button onClick={() => setMode("json")}>{t("configuration.json")}</Button>} /> : <>
            <div className="tr-config-sections">{["shared", "analyses", "ui"].map((key) => <Button key={key} onClick={() => setSelection([key])}>{t(`configuration.section.${key}`)}</Button>)}</div>
            {selectedSchema && selection ? <div className="tr-config-field-editor">
              <h2>{String(selectedSchema.title || selection[selection.length - 1])}</h2><code>{selection.join(".")}</code>
              <Form key={selection.join(".")} schema={selectedSchema as RJSFSchema} formData={selectedValue} validator={validator}
                experimental_defaultFormStateBehavior={NO_DEFAULTS} omitExtraData={false} liveOmit={false}
                uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
                onChange={(event) => { if (JSON.stringify(event.formData) !== JSON.stringify(selectedValue)) edit(selection, event.formData); }}>
                <span />
              </Form>
              {selection.length > 1 ? <Button danger onClick={() => { edit(selection, undefined); setSelection(null); }}>{t("configuration.remove")}</Button> : null}
            </div> : <><p>{t("configuration.selectField")}</p><div className="tr-config-present">{currentFields.map((field) => <Button key={field.path.join(".")} onClick={() => setSelection(field.path)}>{field.title}</Button>)}</div></>}
          </>}
        {parsed.error ? <p className="tr-config-validation" role="status">{t("configuration.invalidJSON")}</p> : validationErrors.length ?
          <div className="tr-config-validation" role="status"><strong>{t("configuration.validation", { count: validationErrors.length })}</strong>
            <ul>{validationErrors.map((item, index) => <li key={index}>{item.stack || item.message}</li>)}</ul></div> : null}
      </main>
    </div> : <p role="status">{t("configuration.loading")}</p>}
    <Modal open={discard !== null} title={t("configuration.discardTitle")} onCancel={() => setDiscard(null)}
      okText={t("configuration.discard")} cancelText={t("configuration.keepEditing")} onOk={() => {
        const next = discard; setDiscard(null);
        if (next?.reload) setReload((value) => value + 1);
        else if (next?.workspace) setWorkspace(next.workspace);
        else void create();
      }}>{t("configuration.discardHint")}</Modal>
  </section>;
}
