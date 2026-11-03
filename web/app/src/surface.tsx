import React from "react";
import { SourceDetailPage } from "./pages/source-detail.tsx";
import { ProductDetailPage } from "./pages/product-detail.tsx";
import { JobsPage, JobDetailPage } from "./pages/jobs.tsx";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { SettingsSection } from "./components/settings-section.tsx";
import { AccountPage } from "./pages/account.tsx";
import { CatalogPage } from "./pages/catalog.tsx";
import { ResearchDetailPage } from "./pages/research-detail.tsx";
import { ResearchPage } from "./pages/research.tsx";
import { TradingPage } from "./pages/trading.tsx";
import { WorkspacePage } from "./pages/workspace.tsx";
import { TestConfigurationPage } from "./pages/test-configuration.tsx";
import { TestBenchPage } from "./pages/test-bench.tsx";
import { AdminFunctionsPage } from "./pages/admin-functions.tsx";
import { TechnicalDocsPage } from "./pages/technical-docs.tsx";
import { ObjectReferenceProvider } from "./components/object-reference-provider.tsx";


export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  return <ObjectReferenceProvider><PageContent pageId={pageId} /></ObjectReferenceProvider>;
}

function PageContent({ pageId }: { pageId: string }): React.ReactElement {
  const { t } = useTranslation();
  if (pageId === "source-detail") return <SourceDetailPage />;
  if (pageId === "product-detail") return <ProductDetailPage />;
  if (pageId === "job-detail") return <JobDetailPage />;
  if (pageId === "jobs") return <JobsPage />;
  if (pageId === "account") return <AccountPage />;
  if (pageId === "settings") return <SettingsSection section="account" />;
  if (["products", "factors", "strategies", "catalog"].includes(pageId)) return <CatalogPage domain={pageId === "catalog" ? "products" : pageId as "products" | "factors" | "strategies"} />;
  if (pageId === "more") return <WorkspacePage />;
  if(pageId === "research-detail" || pageId === "research-report") return <ResearchDetailPage/>;
  if (pageId === "research") return <ResearchPage />;
  if (pageId === "trading") return <TradingPage />;
  if (pageId === "test-bench") return <TestBenchPage />;
  if (pageId === "configuration") return <TestConfigurationPage />;
  if (pageId === "admin") return <AdminFunctionsPage />;
  if (pageId === "technical-docs") return <TechnicalDocsPage />;
  return <Alert type="info" message={t("pageUnavailable")} />;
}
