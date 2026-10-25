import React from "react";
import { JobsPage } from "./pages/jobs.tsx";
import { getPage } from "./registry.ts";
import { PageFrame } from "./frame.tsx";


export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  if (pageId === "jobs") return <JobsPage />;
  return <PageFrame pageId={pageId} />;
}
