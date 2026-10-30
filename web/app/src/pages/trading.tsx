import React, { useEffect, useState } from "react";
import { Alert, Button, Card, Collapse, Descriptions, Empty, Space, Spin, Tabs, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { FunctionPage } from "../components/function-page.tsx";
import { ResultView } from "../components/result-view.tsx";
import { TRDataTable } from "../components/data-table.tsx";
import { request } from "../configuration/api.ts";
import { tradingSnapshot, type TradingMode } from "../trading-model.ts";
import { usePageInstance } from "../page-instance.ts";
import { LocalNodeAccess } from "../components/local-node-access.tsx";
export function TradingPage(): React.ReactElement {
  const { t } = useTranslation(), instance = usePageInstance();
  const [mode, setMode] = useState<TradingMode>("paper"), [revision, setRevision] = useState(0);
  const [capabilities, setCapabilities] = useState<Record<string, any> | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false);
  useEffect(() => { if (instance.active === false) return; const controller = new AbortController(); setLoading(true); setError("");
    request("/api/nautilus/capabilities", { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) setCapabilities(data); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision, instance.active]);
  const snapshot = tradingSnapshot(error ? null : capabilities, mode);
  const connectionRows = [
    { name: t("trading.marketData"), status: "unreported", reason: "" },
    { name: t(mode === "paper" ? "trading.paper" : "trading.live"), status: snapshot.reported ? snapshot.available ? "readOnly" : "unavailable" : "unreported", reason: snapshot.reason },
    { name: t("trading.reconciliation"), status: "unreported", reason: "" },
  ];
  return <FunctionPage title={t("nav.trading")} actions={<Space>{!instance.mobile ? <LocalNodeAccess /> : null}<Button loading={loading} onClick={() => setRevision((value) => value + 1)}>{t("configuration.reload")}</Button></Space>}>
    <Tabs activeKey={mode} onChange={(value) => setMode(value as TradingMode)} items={[{ key: "paper", label: t("trading.paper") }, { key: "live", label: t("trading.live") }]} />
    {error ? <Alert type="error" message={error} /> : null}<Spin spinning={loading}><div className="tr-trading-grid">
      <Card title={t("trading.runtime")} extra={<Tag color={snapshot.available ? "blue" : "default"}>{error ? t("loadFailed") : t(`trading.${snapshot.available ? "readOnly" : snapshot.reported ? "unavailable" : "unreported"}`)}</Tag>}>
        <Descriptions column={1} items={[{ key: "engine", label: t("trading.engine"), children: !error && capabilities ? snapshot.installed ? `NautilusTrader ${snapshot.version}`.trim() : t("trading.notInstalled") : "—" }, { key: "mode", label: t("trading.mode"), children: t(mode === "paper" ? "trading.paper" : "trading.live") }]} />
      </Card>
      <Card title={t("trading.connections")}><TRDataTable rows={connectionRows} rowKey="name" pagination={{ page: 1, pageSize: 10, total: 3, hideOnSinglePage: true, onChange: () => undefined }} columns={[
        { title: t("trading.connection"), dataIndex: "name" },
        { title: t("jobs.status"), dataIndex: "status", render: (value) => <Tag>{t(`trading.${value}`)}</Tag> },
        { title: t("library.description"), dataIndex: "reason", render: (value) => value ? t(`trading.reasons.${value}`, { defaultValue: value }) : "—" },
      ]} /></Card>
      <Card title={t("trading.accounts")}><Empty description={t("trading.accountUnreported")} /></Card>
    </div></Spin>
    {capabilities && !error ? <Collapse ghost items={[{ key: "capabilities", label: t("trading.capabilities"), children: <ResultView value={capabilities} /> }]} /> : null}
  </FunctionPage>;
}
