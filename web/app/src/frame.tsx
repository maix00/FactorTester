import React from "react";
import { useTranslation } from "react-i18next";
import { getPage } from "./registry.ts";

export function PageFrame({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  const { i18n } = useTranslation();
  return (
    <iframe
      key={i18n.language}
      className="tr-page-frame"
      title={page?.title ?? pageId}
      src={`${page?.route ?? "/"}${(page?.route ?? "").includes("?") ? "&" : "?"}presentation=embedded`}
      loading="lazy"
    />
  );
}
