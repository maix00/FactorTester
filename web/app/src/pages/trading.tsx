import React, { useEffect, useState } from "react";
import { Alert, Empty, Spin, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { FunctionPage } from "../components/function-page.tsx";
import { ResultView } from "../components/result-view.tsx";
import { request } from "../configuration/api.ts";
export function TradingPage(): React.ReactElement {
  const { t } = useTranslation();
  const [capabilities, setCapabilities] = useState<unknown>(null), [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController();
    request("/api/nautilus/capabilities", { signal: controller.signal }).then(setCapabilities).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  return <FunctionPage title={t("nav.trading")}><Tabs items={[
    { key: "paper", label: t("trading.paper"), children: <Empty description={t("trading.noBroker")} /> },
    { key: "live", label: t("trading.live"), children: <Empty description={t("trading.noBroker")} /> },
    { key: "capabilities", label: t("trading.capabilities"), children: error ? <Alert type="error" message={error} /> : capabilities ? <ResultView value={capabilities} /> : <Spin /> },
  ]} /></FunctionPage>;
}
