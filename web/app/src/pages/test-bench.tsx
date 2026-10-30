import React, { useEffect, useState } from "react";
import { Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { PageInstanceProvider, usePageInstance } from "../page-instance.ts";
import { TestConfigurationPage } from "./test-configuration.tsx";
import { JobsPage } from "./jobs.tsx";
import { LocalNodeAccess } from "../components/local-node-access.tsx";
import { hasDesktopClientBridge } from "../desktop-client.ts";

type TestBenchTab = "configuration" | "jobs";
const TEST_BENCH_TAB_KEY = "tr.test-bench.tab";

function savedTab(): TestBenchTab {
  try {
    return localStorage.getItem(TEST_BENCH_TAB_KEY) === "jobs" ? "jobs" : "configuration";
  } catch {
    return "configuration";
  }
}

export function TestBenchPage(): React.ReactElement {
  const { t } = useTranslation();
  const instance = usePageInstance();
  const initial = instance.args.testTab;
  const [tab, setTab] = useState<TestBenchTab>(initial || savedTab());

  useEffect(() => {
    if (initial === "configuration" || initial === "jobs") setTab(initial);
  }, [initial]);

  const selectTab = (value: string): void => {
    const next = value === "jobs" ? "jobs" : "configuration";
    setTab(next);
    try { localStorage.setItem(TEST_BENCH_TAB_KEY, next); } catch { /* storage may be disabled */ }
  };

  const configurationInstance = { ...instance, active: instance.active !== false && tab === "configuration" };
  const jobsInstance = { ...instance, active: instance.active !== false && tab === "jobs" };

  return <section className="tr-test-bench-page" aria-label={t("nav.testBench", { defaultValue: "Test bench" })}>
    <div className="tr-test-bench">
      {!instance.mobile || hasDesktopClientBridge(window) ? <header className="tr-function-header tr-test-bench-header"><h1>{t("nav.testBench")}</h1><div className="tr-function-actions">{hasDesktopClientBridge(window) ? <LocalNodeAccess /> : null}</div></header> : null}
      <Tabs activeKey={tab} onChange={selectTab} items={[
        { key: "configuration", label: t("nav.configuration", { defaultValue: "Test" }), children: <PageInstanceProvider value={configurationInstance}><TestConfigurationPage embedded /></PageInstanceProvider> },
        { key: "jobs", label: t("nav.jobs", { defaultValue: "Task queue" }), children: <PageInstanceProvider value={jobsInstance}><JobsPage embedded /></PageInstanceProvider> },
      ]} />
    </div>
  </section>;
}
