import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { matchingFamily, objectDetailURL, type ObjectReferenceValue } from "../object-reference.ts";
import { usePageInstance } from "../page-instance.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { FactorDetail } from "./factor-detail.tsx";
import { ObjectReferenceContext } from "./object-reference.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { ResultView } from "./result-view.tsx";

export function ObjectReferenceProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const { t } = useTranslation();
  const instance = usePageInstance();
  const [stack, setStack] = useState<ObjectReferenceValue[]>([]);
  const current = stack.at(-1);
  const key = current ? JSON.stringify([current.kind, current.ref, current.owner, current.profileKey]) : "";
  const [response, setResponse] = useState<{ key: string; detail?: unknown; error?: string } | null>(null);
  useEffect(() => {
    if (!current) return;
    const url = objectDetailURL(current);
    if (!url) return;
    const controller = new AbortController();
    void request(url, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      if (current.kind === "factorFamily") {
        const match = matchingFamily(Array.isArray(data.families) ? data.families : [], current.ref, current.owner);
        if (!match) throw new Error(t("objectReference.notFoundOrAmbiguous"));
        setResponse({ key, detail: match });
      } else setResponse({ key, detail: data });
    }).catch(reason => { if (!controller.signal.aborted) setResponse({ key, error: String(reason.message || reason) }); });
    return () => controller.abort();
  }, [current, key, t]);
  const open = useCallback((value: ObjectReferenceValue): void => {
    if (value.kind === "product" && instance.id !== "standalone") {
      instance.open("product-detail", { productName: value.ref, productTitle: value.label || value.ref });
      return;
    }
    setStack(previous => [...previous, value]);
  }, [instance.id, instance.open]);
  const title = current ? t(`objectReference.kinds.${current.kind}`) : "";
  const loading = !!current && !!objectDetailURL(current) && response?.key !== key;
  const error = response?.key === key ? response.error : undefined;
  const data = (response?.key === key ? response.detail : null) as Record<string, unknown> | null;
  const selected = current?.kind === "productGroup" ? data?.group : current?.kind === "strategy" ? data?.strategy :
    current?.kind === "strategyFamily" ? data?.template : current?.kind === "profile" ? data?.profile : data;
  return <ObjectReferenceContext.Provider value={open}>{children}{current ? <DetailsPanel title={current.label || current.ref} onClose={() => { setStack([]); setResponse(null); }} width={820}>
    {stack.length > 1 ? <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setStack(previous => previous.slice(0, -1))}>{t("back")}</Button> : null}
    <PropertyGroups groups={[{ key: "reference", title, items: [
      ...(current.label && current.label !== current.ref ? [{ key: "name", label: t("editor.name"), value: current.label }] : []),
      { key: "ref", label: t("objectReference.reference"), value: current.ref, wide: true },
      ...(current.owner ? [{ key: "owner", label: t("library.owner"), value: current.owner }] : []),
    ] }]} />
    {loading ? <Spin tip={t("loading")} /> : error ? <Alert type="error" showIcon message={t("objectReference.loadFailed")} description={error} /> :
      current.kind === "factor" || current.kind === "factorFamily" ? selected ? <FactorDetail detail={selected as Record<string, unknown>} /> : null :
      selected ? <ResultView value={selected} /> : <p className="tr-object-reference-hint">{t("objectReference.knownOnly")}</p>}
  </DetailsPanel> : null}</ObjectReferenceContext.Provider>;
}
