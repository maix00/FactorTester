import React, { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Modal, Pagination, Select, Switch } from "antd";
import Form from "@rjsf/antd";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema } from "@rjsf/utils";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { runRequest } from "../configuration/run.ts";
import { request } from "../configuration/api.ts";
import { PlusOutlined, ReloadOutlined, ArrowLeftOutlined, CodeOutlined, CalendarOutlined, BarChartOutlined, DatabaseOutlined } from "@ant-design/icons";
import { settingsSection } from "../configuration/settings-navigation.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { useConfigurationNavigation, type ConfigurationView } from "../configuration/navigation.ts";
import { configurationStrategies } from "../configuration/strategies.ts";
import { NO_DEFAULTS } from "../configuration/form-options.ts";
import { useStrategyEditor } from "../configuration/strategy-editor.tsx";
import { CodeView } from "../configuration/code-view.tsx";
import { acknowledgeSave, createDraft, fieldSchema, parseDraft, readPath, writePath,
         type Draft, type JSONObject, type Path } from "../configuration/draft.ts";
import "../configuration/editor.css";

interface Workspace { workspace_id: string; title: string }
interface Field { group_title?: string; scope_policy?: string; path: Path; key: string; analysis: string; group: string; title: string; description: string; value: unknown }
interface Contract { schema: JSONObject; catalog: Field[] }
interface Configuration { payload: JSONObject; revision: number }


export function TestConfigurationPage(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState(() => new URLSearchParams(location.search).get("workspace_id") || "");
  const [contract, setContract] = useState<Contract | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const mobile = useCompactLayout();
  const { view, navigate, back } = useConfigurationNavigation();
  const lastFormView = useRef<ConfigurationView>({ page: "overview" });
  if (!["json", "preview"].includes(view.page)) lastFormView.current = view;
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [preview, setPreview] = useState<{ workspace: string; revision: number; text: string; result: JSONObject } | null>(null);
  const previewMatches = !!draft && !!preview && preview.workspace === workspace && preview.revision === draft.revision && preview.text === draft.text && draft.text === draft.savedText;
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [discard, setDiscard] = useState<{ workspace?: string; reload?: boolean } | null>(null);
  const [reload, setReload] = useState(0);
  const activeWorkspace = useRef(workspace);
  activeWorkspace.current = workspace;
  useEffect(() => {
    const url = new URL(location.href);
    if (workspace) url.searchParams.set("workspace_id", workspace);
    else url.searchParams.delete("workspace_id");
    history.replaceState(history.state, "", url.href);
  }, [workspace]);
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
    setLoading(true); setError(""); setConflict(false); setDraft(null);
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
    return (contract?.catalog ?? []).filter((field) => field.scope_policy !== "group_only" && (!needle || `${field.title} ${field.key} ${field.description}`.toLowerCase().includes(needle)));
  }, [contract, query]);

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
    if (!draft || !contract || !parsed.value || saving || strategy.busy || strategy.invalid) return;
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

  const execute = async (submit: boolean): Promise<void> => {
    if (!draft || running || strategy.busy || strategy.invalid || (submit && !previewMatches)) return;
    const currentWorkspace = workspace;
    const currentDraft = draft;
    setRunning(true); setError("");
    try {
      const value = await request(submit ? "/api/runs" : "/api/runs/preview", { method: "POST", body: JSON.stringify(runRequest(workspace, draft)) });
      if (activeWorkspace.current !== currentWorkspace) return;
      if (submit) notify({ code: "configuration.submitted", type: "success", message: t("configuration.submitted"), description: String(value.run_id || "") });
      else { setPreview({ workspace: currentWorkspace, revision: currentDraft.revision, text: currentDraft.text, result: value }); navigate({ page: "preview" }); }
    } catch (reason) { if (activeWorkspace.current === currentWorkspace) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setRunning(false); }
  };

  const strategy = useStrategyEditor({ scope: `${workspace}:${reload}`, text: draft?.text || "{}", view, navigate: (next) => {
      if (view.page === "json" && next.page === "strategy") {
        const found = configurationStrategies(draft?.text || "{}").find(({ binding }) => binding.binding_id === next.id);
        if (found) { navigate({ page: "json", path: [...found.path, String(found.index)] }); return; }
      }
      navigate(next);
    },
    onChange: (text) => setDraft((current) => current ? { ...current, text, source: "form" } : current) });
  const selection = view.path;
  const allFields = (contract?.catalog ?? []).filter((field) => field.analysis === "backtest" && field.scope_policy !== "group_only" && !strategy.parameterKeys.has(field.key));
  const runtimeCatalog = catalog.filter((field) => field.analysis === "backtest" && !strategy.parameterKeys.has(field.key));
  const order = ["data", "execution", "funds", "other"];
  const groups = [...new Map(runtimeCatalog.map((field) => [`${field.analysis}:${settingsSection(field.group)}`, field])).entries()].sort((a, b) => order.indexOf(settingsSection(a[1].group)) - order.indexOf(settingsSection(b[1].group)));
  const selectedField = selection ? allFields.find((field) => field.path.join(".") === selection.join(".")) : undefined;
  const groupID = selectedField ? `${selectedField.analysis}:${settingsSection(selectedField.group)}` : view.id;
  const groupFields = (view.page === "field" && mobile && selectedField) ? [selectedField] : allFields.filter((field) => `${field.analysis}:${settingsSection(field.group)}` === groupID);
  const groupLabel = (field: Field): string => t(`configuration.sections.${settingsSection(field.group)}`);
  const groupName = groups.find(([id]) => id === groupID)?.[1];
  const detail = view.page !== "overview";
  const panelTitle = view.page === "json" ? "JSON" : view.page === "preview" ? "RunSpec" : ["strategy", "strategies", "catalog", "overview"].includes(view.page)
    ? strategy.title : (groupName ? groupLabel(groupName) : t("configuration.runSettings"));
  const openField = (field: Field): void => {
    if (parsed.value && readPath(parsed.value, field.path) === undefined) edit(field.path, field.value);
    navigate({ page: view.page === "json" ? "json" : "field", path: field.path });
  };
  const fieldRow = (field: Field): React.ReactNode => {
    const schema = contract ? fieldSchema(contract.schema, field.path) : {};
    const included = !!parsed.value && readPath(parsed.value, field.path) !== undefined;
    const id = `tr-field-${field.analysis}-${field.key}`;
    return <div key={field.path.join(".")} className={`tr-config-setting-row ${selection?.join(".") === field.path.join(".") ? "is-selected" : ""}`}>
      <label htmlFor={id}>{field.title}</label>
      <div className="tr-config-setting-control">{included ? <Form idPrefix={id} schema={schema as RJSFSchema} formData={readPath(parsed.value, field.path)} validator={validator}
        experimental_defaultFormStateBehavior={NO_DEFAULTS} omitExtraData={false} liveOmit={false}
        uiSchema={{ "ui:label": false, "ui:title": "", "ui:description": "", "ui:submitButtonOptions": { norender: true } }}
        onChange={(event) => { if (JSON.stringify(event.formData) !== JSON.stringify(readPath(parsed.value, field.path))) edit(field.path, event.formData); }}><span /></Form>
        : <Button type="text" icon={<PlusOutlined />} onClick={() => openField(field)}>{t("configuration.add")}</Button>}</div>
      {included ? <Button type="text" className="tr-config-remove" aria-label={`${t("configuration.remove")} ${field.title}`} onClick={() => edit(field.path, undefined)}>×</Button> : null}
    </div>;
  };
  const disabled = !draft || loading || saving || strategy.busy || strategy.invalid || conflict;
  const saveAction = <Button type={mobile ? "primary" : "default"} aria-label={t("configuration.save")} loading={saving} disabled={disabled || !dirty || !!parsed.error || !contract} onClick={() => void save()}>{t("configuration.save")}</Button>;
  const actions = <>{saveAction}
    <Button aria-label={t("configuration.preview")} loading={running} disabled={disabled || dirty} onClick={() => void execute(false)}>{t("configuration.preview")}</Button>
    <Button type="primary" aria-label={t("configuration.run")} disabled={disabled || !previewMatches || running} onClick={() => void execute(true)}>{t("configuration.run")}</Button>
  </>;
  return <section className="tr-config-page" data-detail={detail} aria-label={t("configuration.title")}>
    <header className="tr-config-topbar">
      {mobile && detail ? <Button className="tr-config-back" type="text" icon={<ArrowLeftOutlined />} aria-label={t("back")} onClick={back}>{t(["strategy", "strategies", "catalog"].includes(view.page) ? "configuration.strategies" : "configuration.title")}</Button> : <h1>{t("configuration.title")}</h1>}
      {!mobile || !detail ? <div className="tr-config-workspace">
        <Select aria-label={t("configuration.workspace")} placeholder={t("configuration.workspace")} value={workspace || undefined}
          options={workspaces.map((row) => ({ value: row.workspace_id, label: row.title || row.workspace_id }))}
          onChange={(value: string) => dirty ? setDiscard({ workspace: value }) : setWorkspace(value)} disabled={saving || strategy.busy} />
        <Button type="text" icon={<PlusOutlined />} aria-label={t("configuration.create")} onClick={() => dirty ? setDiscard({ workspace: "" }) : void create()} disabled={saving} />
        <Button type="text" icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => dirty ? setDiscard({ reload: true }) : setReload((value) => value + 1)} disabled={!workspace || saving} />
        <span className={`tr-config-status ${dirty ? "is-dirty" : ""}`} role="status" aria-label={dirty ? t("configuration.unsaved") : t("configuration.savedState")} title={dirty ? t("configuration.unsaved") : t("configuration.savedState")} />
      </div> : null}
      <div className="tr-config-top-actions">{mobile ? <Button type="text" aria-label="JSON" icon={<CodeOutlined />} disabled={!draft} onClick={() => view.page === "json" ? back() : navigate({ page: "json" })}>JSON</Button> :
        <label className="tr-config-json-toggle"><Switch size="small" aria-label="JSON" disabled={!draft} checked={view.page === "json"} onChange={(checked) => navigate(checked ? { page: "json" } : lastFormView.current)} /><span>JSON</span></label>}{!mobile ? actions : null}</div>
    </header>
    {conflict ? <Alert type="warning" showIcon message={t("configuration.conflict")} /> : null}
    {error ? <Alert type="error" showIcon message={error} closable onClose={() => setError("")} /> : null}
    {loading ? <p className="tr-config-loading" role="status">{t("configuration.loading")}</p> : null}
    {!draft ? !loading ? <Empty description={false} /> : null : contract ? <div className="tr-config-layout">
      <aside className="tr-config-sidebar" hidden={mobile && detail}>
        <div className="tr-config-nav-heading"><button type="button" onClick={() => navigate({ page: "strategies" })}>{t("configuration.strategies")}</button>
          <Button type="text" size="small" icon={<PlusOutlined />} aria-label={t("configuration.addStrategy")} onClick={() => navigate({ page: "catalog" })} /></div>
        {strategy.navigation}
        <div className="tr-config-nav-heading tr-config-settings-heading"><button type="button" onClick={() => navigate({ page: "settings" })}>{t("configuration.runSettings")}</button></div>
        <Input.Search aria-label={t("configuration.search")} placeholder={t("configuration.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} allowClear />
        <div className="tr-config-nav-list">{groups.map(([id, field]) => <button type="button" key={id} className={groupID === id ? "is-selected" : ""}
          onClick={() => navigate(view.page === "json" ? { page: "json", path: field.path.slice(0, -1) } : { page: "settings", id })}><span className="tr-config-nav-item-label">{settingsSection(field.group) === "data" ? <CalendarOutlined /> : settingsSection(field.group) === "funds" ? <DatabaseOutlined /> : <BarChartOutlined />}<span>{groupLabel(field)}</span></span><span className="tr-config-chevron">›</span></button>)}</div>
      </aside>
      <main className="tr-config-content" hidden={mobile && !detail}>
        {!mobile || detail ? <div className="tr-config-panel-heading"><h2>{panelTitle}</h2></div> : null}
        {view.page === "json" ? <CodeView text={draft.text} schema={contract.schema} path={view.path} onChange={change} applyExternal={draft.source !== "json"} /> :
          view.page === "preview" ? <pre className="tr-config-preview">{JSON.stringify(preview?.result || {}, null, 2)}</pre> :
          parsed.error ? <Alert type="error" showIcon message={t("configuration.invalidJSON")} action={<Button onClick={() => navigate({ page: "json" })}>JSON</Button>} /> :
          ["overview", "strategy", "strategies", "catalog"].includes(view.page) ? strategy.content : groupFields.length ? <div className="tr-config-field-editor">{groupFields.map(fieldRow)}</div> :
          <div className="tr-config-setting-catalog"><Input.Search aria-label={t("configuration.search")} placeholder={t("configuration.search")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} allowClear />
            <div className="tr-config-choice-list">{runtimeCatalog.slice((page - 1) * 12, page * 12).map((field) => <button type="button" key={field.path.join(".")} onClick={() => openField(field)}><span>{field.title}</span><span className="tr-config-chevron">{readPath(parsed.value, field.path) === undefined ? "＋" : "›"}</span></button>)}</div>
            <Pagination simple size="small" current={page} total={runtimeCatalog.length} pageSize={12} onChange={setPage} hideOnSinglePage /></div>}
        {validationErrors.length ? <div className="tr-config-validation" role="status"><strong>{t("configuration.validation", { count: validationErrors.length })}</strong>
          <ul>{validationErrors.map((item, index) => <li key={index}>{item.stack || item.message}</li>)}</ul></div> : null}
      </main>
    </div> : <p role="status">{t("configuration.loading")}</p>}
    {mobile && draft ? <footer className="tr-config-mobile-actions">{["strategy", "field", "json"].includes(view.page) ? saveAction : actions}</footer> : null}
    <Modal open={discard !== null} title={t("configuration.discardTitle")} onCancel={() => setDiscard(null)}
      okText={t("configuration.discard")} cancelText={t("configuration.keepEditing")} onOk={() => {
        const next = discard; setDiscard(null);
        if (next?.reload) setReload((value) => value + 1);
        else if (next?.workspace) setWorkspace(next.workspace);
        else void create();
      }}>{t("configuration.discardHint")}</Modal>
  </section>;
}
