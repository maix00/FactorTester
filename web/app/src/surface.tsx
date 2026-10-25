import React from "react";
import { JobsPage } from "./pages/jobs.tsx";
import { getPage } from "./registry.ts";
import { PageFrame } from "./frame.tsx";
import { AccountPage } from "./pages/account.tsx";
import { CatalogPage } from "./pages/catalog.tsx";
import { ResearchPage } from "./pages/research.tsx";
import { TradingPage } from "./pages/trading.tsx";


export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  if (pageId === "jobs") return <JobsPage />;
  if (pageId === "account") return <AccountPage />;
  if (pageId === "catalog") return <CatalogPage />;
  if (pageId === "research") return <ResearchPage />;
  if (pageId === "trading") return <TradingPage />;
  return <PageFrame pageId={pageId} />;
}
