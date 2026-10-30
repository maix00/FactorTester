import React from "react";
import { SourceDetailPage } from "./pages/source-detail.tsx";
import { ProductDetailPage } from "./pages/product-detail.tsx";
import { JobsPage, JobDetailPage } from "./pages/jobs.tsx";
import { getPage } from "./registry.ts";
import { PageFrame } from "./frame.tsx";
import { AccountPage } from "./pages/account.tsx";
import { CatalogPage } from "./pages/catalog.tsx";
import { ResearchPage } from "./pages/research.tsx";
import { TradingPage } from "./pages/trading.tsx";
import { WorkspacePage } from "./pages/workspace.tsx";
import { TestConfigurationPage } from "./pages/test-configuration.tsx";
import { TestBenchPage } from "./pages/test-bench.tsx";
import { AdminFunctionsPage } from "./pages/admin-functions.tsx";
import { TechnicalDocsPage } from "./pages/technical-docs.tsx";


export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  if (pageId === "source-detail") return <SourceDetailPage />;
  if (pageId === "product-detail") return <ProductDetailPage />;
  if (pageId === "job-detail") return <JobDetailPage />;
  if (pageId === "jobs") return <JobsPage />;
  if (pageId === "account") return <AccountPage />;
  if (["products", "factors", "strategies", "catalog"].includes(pageId)) return <CatalogPage domain={pageId === "catalog" ? "products" : pageId as "products" | "factors" | "strategies"} />;
  if (pageId === "more") return <WorkspacePage />;
  if (pageId === "research") return <ResearchPage />;
  if (pageId === "trading") return <TradingPage />;
  if (pageId === "test-bench") return <TestBenchPage />;
  if (pageId === "configuration") return <TestConfigurationPage />;
  if (pageId === "admin") return <AdminFunctionsPage />;
  if (pageId === "technical-docs") return <TechnicalDocsPage />;
  return <PageFrame pageId={pageId} />;
}
