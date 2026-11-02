import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Form, Input, Space, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { notify } from "../notifications/core.ts";
import { referenceForField } from "../object-reference.ts";
import { applicabilityDraft, applicabilityValue, type ApplicabilityDraft, type ApplicabilityField } from "../research-evidence-model.ts";
import { ObjectReference } from "./object-reference.tsx";

type Schema = { sections: { id: string; label_zh?: string }[]; fields: ApplicabilityField[] };
type Loaded = { schema: Schema; initial: Record<string, unknown>; revision: string; canManage: boolean };
const objectValue = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

/** Editable scope is guarded by the server's revision, not by a prior GET alone. */
export function ResearchEvidenceEditor({ evidenceRef, onCancel, onSaved }: { evidenceRef: string; onCancel: () => void; onSaved: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [draft, setDraft] = useState<ApplicabilityDraft>({});
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const pending = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      request(`/api/research-evidence/${encodeURIComponent(evidenceRef)}`, { signal: controller.signal }),
      request("/api/research-evidence/applicability/schema", { signal: controller.signal }),
    ]).then(([detail, response]) => {
      if (controller.signal.aborted) return;
      const schema = response.schema as Schema;
      if (!objectValue(detail.evidence) || !objectValue(detail.evidence.applicability) || !schema || !Array.isArray(schema.sections) || !Array.isArray(schema.fields)) throw new Error(t("researchDetail.invalidResponse"));
      const initial = detail.evidence.applicability;
      const revision = typeof detail.evidence.applicability_revision === "string" ? detail.evidence.applicability_revision : "";
      setLoaded({ schema, initial, revision, canManage: detail.access?.can_manage === true });
      setDraft(applicabilityDraft(initial, schema.fields));
    }).catch(reason => { if (!controller.signal.aborted) setLoadError(reason instanceof Error ? reason.message : String(reason)); });
    return () => controller.abort();
  }, [evidenceRef, t]);
  const save = async (): Promise<void> => {
    if (!loaded || !loaded.canManage || !/^sha256:[0-9a-f]{64}$/.test(loaded.revision) || pending.current || conflict) return;
    pending.current = true; setBusy(true);
    try {
      await request(`/api/research-evidence/${encodeURIComponent(evidenceRef)}/applicability`, {
        method: "PATCH", body: JSON.stringify({ expected_applicability_revision: loaded.revision, applicability: applicabilityValue(loaded.initial, loaded.schema.fields, draft) }),
      });
      notify({ code: "research.evidence.scope.saved", type: "success", message: t("researchEvidence.saved") });
      onSaved();
    } catch (reason) {
      const error = reason as Error & { code?: string };
      if (error.code === "evidence_applicability_conflict") {
        setConflict(true);
        notify({ code: "research.evidence.scope.conflict", type: "warning", message: t("researchEvidence.conflict") });
      } else notify({ code: "research.evidence.scope.failed", type: "error", message: t("researchDetail.operationFailed"), description: error.message });
    } finally { pending.current = false; setBusy(false); }
  };
  if (loadError) return <Alert type="error" showIcon message={t("loadFailed")} description={loadError} action={<Button onClick={onCancel}>{t("back")}</Button>} />;
  if (!loaded) return <Spin tip={t("loading")} />;
  const readOnly = !loaded.canManage || !/^sha256:[0-9a-f]{64}$/.test(loaded.revision);
  const fields = loaded.schema.fields.filter(field => field.exposed !== false && ["string_array", "reference", "time_window"].includes(field.type));
  const update = (key: string, value: string): void => setDraft(current => ({ ...current, [key]: value }));
  return <section>
    <h3>{t("researchEvidence.edit")}</h3>
    {readOnly ? <Alert type="info" showIcon message={loaded.canManage ? t("researchEvidence.unverified") : t("researchEvidence.readOnly")} /> : null}
    {conflict ? <Alert type="warning" showIcon message={t("researchEvidence.conflict")} description={t("researchEvidence.conflictHelp")} /> : null}
    <Form layout="vertical" onFinish={() => void save()}>
      {loaded.schema.sections.map(section => {
        const visible = fields.filter(field => field.section === section.id);
        if (!visible.length) return null;
        return <section key={section.id}><h4>{t(`researchEvidence.sections.${section.id}`, { defaultValue: section.label_zh || section.id })}</h4>
          {visible.map(field => {
            const label = t(`researchEvidence.fields.${field.name}`, { defaultValue: field.label_zh || field.name });
            const raw = draft[field.name] || "";
            const refs = (field.type === "string_array" ? raw.split("\n") : [raw]).map(value => referenceForField(field.name, value)).filter(value => value !== null);
            return <Form.Item key={field.name} label={label} extra={field.type === "string_array" ? t("researchEvidence.onePerLine") : undefined}>
              {field.type === "time_window" ? <Space.Compact block><Input aria-label={`${label} · ${t("market.start")}`} disabled={readOnly} placeholder={t("market.start")} value={draft[`${field.name}.start`] || ""} onChange={event => update(`${field.name}.start`, event.target.value)} /><Input aria-label={`${label} · ${t("market.end")}`} disabled={readOnly} placeholder={t("market.end")} value={draft[`${field.name}.end`] || ""} onChange={event => update(`${field.name}.end`, event.target.value)} /></Space.Compact>
                : field.type === "string_array" ? <Input.TextArea aria-label={label} autoSize={{minRows: 2, maxRows: 6}} disabled={readOnly} value={raw} onChange={event => update(field.name, event.target.value)} />
                  : <Input aria-label={label} disabled={readOnly} value={raw} onChange={event => update(field.name, event.target.value)} />}
              {refs.length ? <details><summary>{t("researchEvidence.viewReferences", { count: refs.length })}</summary>{refs.map((value, index) => <div key={`${value.ref}:${index}`}><ObjectReference value={value} /></div>)}</details> : null}
            </Form.Item>;
          })}
        </section>;
      })}
      <Space><Button type="primary" htmlType="submit" loading={busy} disabled={readOnly || conflict}>{t("configuration.save")}</Button><Button onClick={onCancel} disabled={busy}>{t("configuration.cancel")}</Button></Space>
    </Form>
  </section>;
}
