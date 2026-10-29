import React from "react";
import { Collapse } from "antd";
import { useTranslation } from "react-i18next";
import { PropertyGroups } from "./property-groups.tsx";
import { ResultView } from "./result-view.tsx";

export function ServerSummary({ data }: { data: Record<string, unknown> }): React.ReactElement {
  const { t } = useTranslation();
  return <section aria-label={t("serverSummary.title")}>
    <PropertyGroups groups={[{ key: "server", title: t("serverSummary.title"), items: [
      { key: "id", label: t("serverSummary.id"), value: data.server_id },
      { key: "role", label: t("serverSummary.role"), value: data.role },
      { key: "port", label: t("serverSummary.port"), value: data.manager_port },
      { key: "endpoint", label: t("serverSummary.endpoint"), value: data.advertised_public_endpoint },
    ] }]} />
    <Collapse ghost items={[{ key: "raw", label: t("serverSummary.details"), children: <ResultView value={data} /> }]} />
  </section>;
}
