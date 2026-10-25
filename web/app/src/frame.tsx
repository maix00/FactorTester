import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { getPage } from "./registry.ts";

export function PageFrame({ pageId, canvas = false }: { pageId: string; canvas?: boolean }): React.ReactElement {
  const page = getPage(pageId);
  const { t, i18n } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const query = canvas ? "presentation=canvas" : "presentation=embedded";
  return (
    <div className="tr-frame-shell" aria-busy={!loaded}>
      {!loaded ? <div className="tr-frame-loading">{t("loading")}</div> : null}
      <iframe
        key={`${i18n.language}:${canvas}`}
        className="tr-page-frame"
        title={page?.title ?? pageId}
        src={`${page?.route ?? "/"}${(page?.route ?? "").includes("?") ? "&" : "?"}${query}`}
        loading="lazy"
        onLoad={() => setLoaded(true)}
      />
    </div>
  );
}
