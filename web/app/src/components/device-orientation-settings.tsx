import React, { useEffect, useState } from "react";
import { Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";

type Orientation = "portrait" | "landscape" | "system";
type Handler = {postMessage: (message: Record<string, string>) => Promise<unknown>};

export function orientationHandler(): Handler | null {
  const handler = (window as unknown as {webkit?: {messageHandlers?: {tradeResearchOrientation?: Handler}}})
    .webkit?.messageHandlers?.tradeResearchOrientation;
  return typeof handler?.postMessage === "function" ? handler : null;
}

function orientation(value: unknown): Orientation {
  if (typeof value !== "object" || value === null) throw new Error("invalid orientation reply");
  const reply = value as {success?: unknown; orientation?: unknown};
  if (reply.success !== true || !["portrait", "landscape", "system"].includes(String(reply.orientation))) throw new Error("invalid orientation reply");
  return reply.orientation as Orientation;
}

export function DeviceOrientationSettings(): React.ReactElement {
  const {t} = useTranslation(), [value, setValue] = useState<Orientation | null>(null), [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    orientationHandler()?.postMessage({action: "current"}).then(result => { if (active) setValue(orientation(result)); })
      .catch(() => { if (active) notify({code:"device.orientation.read",type:"error",message:t("deviceOrientation.failed")}); });
    return () => { active = false; };
  }, [t]);
  const setOrientation = async (next: Orientation): Promise<void> => {
    setBusy(true);
    try { setValue(orientation(await orientationHandler()?.postMessage({action:"set", orientation:next}))); }
    catch { notify({code:"device.orientation.write",type:"error",message:t("deviceOrientation.failed")}); }
    finally { setBusy(false); }
  };
  if (!value) return <Spin />;
  return <Select size="small" aria-label={t("deviceOrientation.title")} value={value} disabled={busy} className="tr-appearance-select" popupClassName="tr-appearance-dropdown" popupMatchSelectWidth={false}
      onChange={(next: Orientation) => void setOrientation(next)} options={(["portrait", "landscape", "system"] as Orientation[])
        .map(key => ({value:key, label:t(`deviceOrientation.${key}`)}))} />;
}
