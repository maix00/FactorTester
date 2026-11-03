import React, { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { SettingsFields } from "./settings-fields.tsx";

export function ClientDownloads(): React.ReactElement {
  const { t } = useTranslation();
  const [release, setRelease] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setRelease(null); setError("");
    request("/api/client/releases/beta.json", { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setRelease(value); })
      .catch(() => { if (!controller.signal.aborted) setError(t("clientDownloads.unavailable")); });
    return () => controller.abort();
  }, [revision, t]);
  if (error) return <Alert type="info" message={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} />;
  if (!release) return <Spin />;
  let href: string | undefined;
  try {
    const raw = release.dmg_url || release.url;
    if (typeof raw === "string" && raw) {
      const url = new URL(raw, location.href);
      if (!url.username && !url.password && (url.protocol === "https:" || (url.protocol === "http:" && url.origin === location.origin))) href = url.href;
    }
  } catch { /* An invalid release URL cannot become a download action. */ }
  return <SettingsFields items={[
    { key: "version", label: t("clientDownloads.version"), value: release.version || release.short_version || t("clientDownloads.unavailable") },
    { key: "macos", label: "macOS", value: true, render: () => <Button size="small" icon={<DownloadOutlined aria-hidden />} href={href} disabled={!href} target="_blank" rel="noopener noreferrer">{t("clientDownloads.downloadMac")}</Button> },
    { key: "windows", label: "Windows", value: t("clientDownloads.preparing") },
    { key: "linux", label: "Linux", value: t("clientDownloads.preparing") },
  ]} />;
}
