import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { Button, Input, Pagination, Select, Spin } from "antd";
import Form from "@rjsf/antd";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema, WidgetProps } from "@rjsf/utils";
import { useTranslation } from "react-i18next";
import { request } from "./api.ts";
import { parseDraft, readPath, writePath, type JSONObject } from "./draft.ts";
import { FactorPicker } from "../components/library-picker.tsx";
import { LibraryCreate } from "../components/library-create.tsx";
import { NO_DEFAULTS } from "./form-options.ts";
import type { ConfigurationView } from "./navigation.ts";
import { appendStrategy, attachFrozenFactors, configurationStrategies, patchStrategy, templateInputs, strategyDefaults, strategySchema, type StrategyChoice } from "./strategies.ts";

function ReferenceWidget(props: WidgetProps): React.ReactElement {
  const [rows, setRows] = useState<JSONObject[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const factor = props.options.referenceType === "factor_ref";
  useEffect(() => {
    if (factor) return;
    const controller = new AbortController(); setLoading(true);
    request(factor ? "/api/factor-library/factors" : "/api/product-library/product-groups?view=summary", { signal: controller.signal })
      .then((data) => setRows(factor ? data.factors ?? [] : data.groups ?? []))
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [factor]);
  const reference = (row: JSONObject): string => String(factor ? row.ref || row.factor_ref || "" : row.ref || row.group_ref || row.id || "");
  const options = [...new Map(rows.map((row) => [reference(row), { value: reference(row), label: String(row.name || row.title || row.factor_alias || row.alias || reference(row)) }])).values()];
  if (props.value && !options.some((item) => item.value === props.value)) options.unshift({ value: props.value, label: props.value });
  if (factor) return <FactorPicker label={props.label} value={props.value} disabled={props.disabled || props.readonly} onSelect={(record) => { props.formContext?.rememberFactor?.(String(record.ref), record); props.onChange(String(record.ref)); }} />;
  return <><Select id={props.id} aria-label={props.label} value={props.value || undefined} showSearch optionFilterProp="label" style={{ width: "100%" }}
    options={options} loading={loading} disabled={props.disabled || props.readonly} onChange={(value: string) => {
      const row = rows.find((item) => reference(item) === value);
      if (factor && row) props.formContext?.rememberFactor?.(value, row);
      props.onChange(value);
    }} />{error ? <span role="alert">{error}</span> : null}</>;
}

interface StrategyEditorOptions { scope: string; text: string; onChange: (text: string) => void; view: ConfigurationView; navigate: (view: ConfigurationView) => void }
export function useStrategyEditor({ scope, text, onChange, view, navigate }: StrategyEditorOptions): {
  navigation: React.ReactNode; content: React.ReactNode; title: string; busy: boolean; invalid: boolean; parameterKeys: Set<string>;
} {
  const { t, i18n } = useTranslation();
  const formId = useId();
  const [templates, setTemplates] = useState<StrategyChoice[]>([]);
  const [users, setUsers] = useState<StrategyChoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(0);
  const [reading, setReading] = useState(false);
  const [creating, setCreating] = useState(false);
  const factorRows = useRef(new Map<string, JSONObject>());
  const latest = useRef({ text, onChange, scope, page: view.page }); latest.current = { text, onChange, scope, page: view.page };
  const detailRequests = useRef(new Map<string, Promise<JSONObject>>());
  const generation = useRef(0);
  const catalog = view.page === "catalog";
  useEffect(() => {
    const controller = new AbortController();
    request("/api/strategy-library/factor-strategies", { signal: controller.signal })
      .then((data) => setTemplates(data.items ?? []))
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!catalog) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setReading(true);
      request(`/api/strategy-library/strategies?scope=all&page=${page}&limit=20&query=${encodeURIComponent(query)}`, { signal: controller.signal })
        .then((data) => { setUsers(data.items ?? []); setTotal(data.total ?? 0); })
        .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
        .finally(() => { if (!controller.signal.aborted) setReading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [catalog, query, page]);
  useEffect(() => { generation.current += 1; setPending(0); setError(""); return () => { generation.current += 1; }; }, [scope]);
  const rows = useMemo(() => configurationStrategies(text), [text]);
  const selected = rows.find(({ binding }) => binding.binding_id === view.id);
  const template = templates.find((item) => item.template_ref === selected?.binding.template_ref);
  const name = (choice: StrategyChoice): string => t(`configuration.templates.${choice.template_ref?.split(":").pop()}`, { defaultValue: choice.name });
  const localized = (choice: StrategyChoice): StrategyChoice => ({ ...choice, configuration_schema: { fields: (choice.configuration_schema?.fields ?? []).map((field) => ({ ...field,
    label: t(`configuration.strategyFields.${field.key}`, { defaultValue: i18n.language.startsWith("en") ? field.key : field.label }) })) } });
  const bindingValues = (binding: JSONObject): JSONObject => ({ ...(binding.parameters as JSONObject), ...(binding.factor_bindings as JSONObject), product_group_ref: binding.product_group_ref });
  const values = selected ? bindingValues(selected.binding) : {};
  const schema = template ? strategySchema(localized(template), values) : {};
  const uiSchema: JSONObject = { "ui:description": "", "ui:submitButtonOptions": { norender: true } };
  for (const field of template?.configuration_schema?.fields ?? []) {
    if (["factor_ref", "product_group_ref"].includes(field.type)) uiSchema[field.key] = { "ui:widget": "reference", "ui:options": { referenceType: field.type } };
    else if (field.values) uiSchema[field.key] = { "ui:enumNames": field.values.map((value) => t(`configuration.values.${value}`, { defaultValue: value })) };
  }
  const rawFactors = readPath(parseDraft(text).value, ["shared", "factors"]);
  const frozenRefs = new Set((Array.isArray(rawFactors) ? rawFactors : []).filter((item) => item && typeof item === "object").map((item) => item.ref));
  const identifiers = rows.map(({ binding }) => String(binding.strategy_id || binding.target_strategy_id || "").trim());
  const invalid = identifiers.some((id) => !id) || new Set(identifiers).size !== identifiers.length || rows.some(({ binding }) => {
    if (!binding.template_ref) return false;
    const definition = templates.find((item) => item.template_ref === binding.template_ref);
    return !definition || validator.validateFormData(bindingValues(binding), strategySchema(definition, bindingValues(binding)) as RJSFSchema).errors.length > 0
      || Object.values((binding.factor_bindings as JSONObject) || {}).some((ref) => !frozenRefs.has(ref));
  });
  const getFactor = async (ref: string): Promise<JSONObject> => {
    const cached = factorRows.current.get(ref);
    const owner = cached?.owner_username ? `&owner_username=${encodeURIComponent(String(cached.owner_username))}` : "";
    const key = `${ref}:${owner}`;
    let pending = detailRequests.current.get(key);
    if (!pending) {
      pending = request(`/api/factor-library/factors/detail?factor_ref=${encodeURIComponent(ref)}${owner}`).then((data) => data.factor as JSONObject);
      detailRequests.current.set(key, pending);
      pending.catch(() => detailRequests.current.delete(key));
    }
    return pending;
  };
  const hydrate = async (bindingId: string, refs: string[]): Promise<void> => {
    if (!refs.length) return;
    const currentGeneration = generation.current;
    const currentScope = scope;
    setPending((count) => count + 1); setError("");
    try {
      const factors = await Promise.all([...new Set(refs)].map(getFactor));
      if ((generation.current !== currentGeneration || latest.current.scope !== currentScope)) return;
      const current = configurationStrategies(latest.current.text).find(({ binding }) => binding.binding_id === bindingId)?.binding;
      if (!current) return;
      const used = new Set(Object.values((current.factor_bindings as JSONObject) || {}));
      const relevant = factors.filter((factor) => used.has(factor.ref));
      if (relevant.length) latest.current.onChange(attachFrozenFactors(latest.current.text, relevant));
    } catch (reason) { if ((generation.current === currentGeneration && latest.current.scope === currentScope)) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { if ((generation.current === currentGeneration && latest.current.scope === currentScope)) setPending((count) => count - 1); }
  };
  const add = async (choice: StrategyChoice): Promise<void> => {
    setError("");
    let index = rows.length + 1;
    while (rows.some(({ binding }) => (binding.strategy_id || binding.target_strategy_id) === `TR-${String(index).padStart(2, "0")}`)) index += 1;
    const id = `TR-${String(index).padStart(2, "0")}`;
    const defaults = strategyDefaults(choice);
    const currentGeneration = generation.current;
    const currentScope = scope;
    try {
      if (choice.template_ref) {
        for (const field of choice.configuration_schema?.fields ?? []) if (["factor_ref", "product_group_ref"].includes(field.type)) defaults[field.key] = "";
        latest.current.onChange(appendStrategy(latest.current.text, choice, defaults, id, []));
      } else {
        setPending((count) => count + 1);
        const refs = Object.values((choice.current_revision?.requirements?.factor_bindings as JSONObject) || {}).map(String);
        const factors = await Promise.all([...new Set(refs)].map(getFactor));
        if ((generation.current !== currentGeneration || latest.current.scope !== currentScope) || latest.current.page !== "catalog") return;
        latest.current.onChange(appendStrategy(latest.current.text, choice, defaults, id, factors));
      }
      navigate({ page: "strategy", id: `tr-strategy-binding:${id}` });
    } catch (reason) { if ((generation.current === currentGeneration && latest.current.scope === currentScope)) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { if (!choice.template_ref && (generation.current === currentGeneration && latest.current.scope === currentScope)) setPending((count) => count - 1); }
  };
  const navigation = <div className="tr-config-nav-list">{rows.map(({ binding }) => <button key={String(binding.binding_id)} type="button"
    className={view.page === "strategy" && view.id === binding.binding_id ? "is-selected" : ""} onClick={() => navigate({ page: "strategy", id: String(binding.binding_id) })}>
    <span>{String(binding.strategy_id || binding.target_strategy_id)}</span><span className="tr-config-chevron">›</span></button>)}</div>;
  const errors = error ? <div className="tr-config-validation" role="alert">{error}</div> : null;
  let content: React.ReactNode;
  if (catalog && creating) content = <LibraryCreate kind="strategy" onCancel={() => setCreating(false)} onCreated={(value) => { setCreating(false); void add(value as unknown as StrategyChoice); }} />;
  else if (catalog) content = <div className="tr-config-strategy-catalog"><Button type="primary" onClick={() => setCreating(true)}>{t("editor.newStrategy")}</Button>
    <Input.Search aria-label={t("configuration.strategies")} placeholder={t("configuration.searchStrategies")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
    <Spin spinning={reading || pending > 0}><div className="tr-config-choice-list">{[...templates.filter((item) => !query || `${item.name} ${item.strategy_ref}`.toLowerCase().includes(query.toLowerCase())), ...users].map((item) =>
      <button type="button" key={item.strategy_ref} disabled={pending > 0} onClick={() => void add(item)}><span><strong>{name(item)}</strong><small>{t(`configuration.scope.${item.library_scope || "user_custom"}`, { defaultValue: item.library_scope || "user" })}</small></span><span className="tr-config-chevron">＋</span></button>)}</div></Spin>
    <Pagination size="small" current={page} total={total} pageSize={20} onChange={setPage} hideOnSinglePage />{errors}</div>;
  else if (selected) content = <div className="tr-config-strategy-form">
    <div className="tr-config-inline-row"><label htmlFor="tr-strategy-name">{t("configuration.strategyId")}</label><Input id="tr-strategy-name" value={String(selected.binding.strategy_id || selected.binding.target_strategy_id)} onChange={(event) =>
      onChange(patchStrategy(text, String(selected.binding.binding_id), selected.binding.template_ref ? { strategy_id: event.target.value } : { target_strategy_id: event.target.value }))} /></div>
    <div className="tr-config-inline-row"><label>{t("configuration.strategy")}</label>{template ? <Select aria-label={t("configuration.strategy")} value={template.template_ref}
      options={templates.map((item) => ({ value: item.template_ref, label: name(item) }))} onChange={(ref: string) => {
        const next = templates.find((item) => item.template_ref === ref)!;
        const defaults = { ...strategyDefaults(next), ...((selected.binding.factor_bindings as JSONObject) || {}), product_group_ref: selected.binding.product_group_ref };
        onChange(patchStrategy(latest.current.text, String(selected.binding.binding_id), { template_ref: next.template_ref, revision_ref: next.revision_ref, ...templateInputs(next, defaults) }));
      }} /> : <span>{String((selected.binding.source as JSONObject)?.strategy_ref || selected.binding.template_ref || "")}</span>}</div>
    {template ? <Form idPrefix={`tr-strategy-${formId}`} key={String(selected.binding.binding_id)} schema={schema as RJSFSchema} formData={values} validator={validator} uiSchema={uiSchema} widgets={{ reference: ReferenceWidget }}
      experimental_defaultFormStateBehavior={NO_DEFAULTS} formContext={{ rememberFactor: (ref: string, row: JSONObject) => factorRows.current.set(ref, row) }}
      onChange={(event) => {
        const next = event.formData || {};
        if (JSON.stringify(next) === JSON.stringify(values)) return;
        const patch = templateInputs(template, next);
        onChange(patchStrategy(latest.current.text, String(selected.binding.binding_id), patch));
        void hydrate(String(selected.binding.binding_id), Object.values(patch.factor_bindings as JSONObject).filter((ref) => typeof ref === "string" && ref && !frozenRefs.has(ref)).map(String));
      }}><span /></Form> : null}
    {errors}<Button danger type="text" onClick={() => { onChange(writePath(text, selected.path, (readPath(parseDraft(text).value, selected.path) as JSONObject[]).filter((item) => item.binding_id !== selected.binding.binding_id))); navigate({ page: "strategies" }); }}>{t("configuration.removeStrategy")}</Button>
  </div>;
  else content = <div className="tr-config-overview-list">{navigation}<Button type="dashed" block onClick={() => navigate({ page: "catalog" })}>{t("configuration.addStrategy")}</Button>{errors}</div>;
  const parameterKeys = new Set(templates.flatMap((item) => item.configuration_schema?.fields.map((field) => field.key) || []));
  return { navigation, content, parameterKeys, title: catalog ? t("configuration.addStrategy") : selected ? String(selected.binding.strategy_id || selected.binding.target_strategy_id) : t("configuration.strategies"), busy: pending > 0, invalid };
}
