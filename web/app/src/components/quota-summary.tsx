import React from "react";
import { Alert, Collapse, Progress } from "antd";
import { useTranslation } from "react-i18next";
import { PropertyGroups } from "./property-groups.tsx";
import { ResultView } from "./result-view.tsx";

function bytes(value: unknown): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return undefined;
  if (value < 1024) return `${value} B`;
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / (1024 ** power)).toFixed(2)} ${["KiB", "MiB", "GiB", "TiB"][power - 1]}`;
}

/** The job-storage response is a local measurement, not the federated quota inventory. */
export function QuotaSummary({ data }: { data: Record<string, unknown> }): React.ReactElement {
  const { t } = useTranslation();
  const usage = typeof data.usage_bytes === "number" && Number.isFinite(data.usage_bytes) && data.usage_bytes >= 0 ? data.usage_bytes : null;
  const quota = typeof data.quota_bytes === "number" && Number.isFinite(data.quota_bytes) && data.quota_bytes > 0 ? data.quota_bytes : null;
  const percent = usage !== null && quota !== null ? (usage / quota) * 100 : null;
  return <section aria-label={t("quota.localTitle")}>
    <Alert type="info" showIcon message={t("quota.partial")} />
    <h3>{t("quota.localTitle")}</h3>
    {percent !== null ? <Progress percent={Math.min(percent, 100)} status={percent > 100 ? "exception" : "normal"} format={() => `${percent.toFixed(1)}%`} /> : null}
    <PropertyGroups groups={[{ key: "usage", title: t("quota.measurement"), items: [
      { key: "usage", label: t("quota.usage"), value: bytes(data.usage_bytes) },
      { key: "limit", label: t("quota.limit"), value: bytes(data.quota_bytes) },
      { key: "artifacts", label: t("quota.artifacts"), value: bytes(data.artifact_bytes) },
      { key: "server", label: t("quota.server"), value: data.storage_server_id },
    ] }]} />
    <Collapse ghost items={[{ key: "raw", label: t("quota.details"), children: <ResultView value={data} /> }]} />
  </section>;
}
