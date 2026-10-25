import React from "react";
import { useTranslation } from "react-i18next";
import { getPage } from "./registry.ts";

export function PageFrame({ pageId, canvas = false }: { pageId: string; canvas?: boolean }): React.ReactElement {
  const page = getPage(pageId);
  const { i18n } = useTranslation();
  const query = canvas ? "presentation=canvas" : "presentation=embedded";
  return (
    <iframe
      key={`${i18n.language}:${canvas}`}
      className="tr-page-frame"
      title={page?.title ?? pageId}
      src={`${page?.route ?? "/"}${(page?.route ?? "").includes("?") ? "&" : "?"}${query}`}
      loading="lazy"
    />
  );
}
