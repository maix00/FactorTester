import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { getPage } from "./registry.ts";
import { pageFrameSrc } from "./frame-url.ts";

export function PageFrame({ pageId, canvas = false }: { pageId: string; canvas?: boolean }): React.ReactElement {
  const page = getPage(pageId);
  const { t, i18n } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="tr-frame-shell" aria-busy={!loaded}>
      {!loaded ? <div className="tr-frame-loading">{t("loading")}</div> : null}
      <iframe
        key={`${i18n.language}:${canvas}`}
        className="tr-page-frame"
        title={page?.title ?? pageId}
        src={pageFrameSrc(page?.route ?? "/", canvas)}
        loading="lazy"
        onLoad={() => setLoaded(true)}
      />
    </div>
  );
}
