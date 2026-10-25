import React from "react";
import { getPage } from "./registry.ts";


export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  return (
    <iframe
      className="tr-page-frame"
      title={page?.title ?? pageId}
      src={`${page?.route ?? "/"}${(page?.route ?? "").includes("?") ? "&" : "?"}presentation=embedded`}
      loading="lazy"
    />
  );
}
