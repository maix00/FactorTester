import React from "react";
import { JobsPage } from "./pages/jobs.tsx";
import { getPage } from "./registry.ts";


export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  if (pageId === "jobs") return <JobsPage />;
  return (
    <iframe
      className="tr-page-frame"
      title={page?.title ?? pageId}
      src={`${page?.route ?? "/"}${(page?.route ?? "").includes("?") ? "&" : "?"}presentation=embedded`}
      loading="lazy"
    />
  );
}
