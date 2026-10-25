import React from "react";
import { pagesForScope } from "../registry.ts";
import { useTranslation } from "react-i18next";
import i18n, { persistLanguage } from "../i18n.ts";
import { PageIcon } from "../icon.tsx";

const RECENT_KEY = "tr.mobile.recent";

function recentIds(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function WorkspacePage(): React.ReactElement {
  const { t } = useTranslation();
  const recent = recentIds();
  const pages = pagesForScope("mobile")
    .filter((page) => page.id !== "workspace")
    .sort((a, b) => {
      const ai = recent.indexOf(a.id);
      const bi = recent.indexOf(b.id);
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
    });
  return (
    <section className="tr-mobile-workspace">
      <header className="tr-mobile-workspace-header">
        <div>
          <h1>{t("workspace.title")}</h1>
          <p>{t("workspace.desc")}</p>
        </div>
        <select
          className="tr-mobile-language"
          aria-label={t("language")}
          value={i18n.language.startsWith("en") ? "en" : "zh"}
          onChange={(event) => {
            const language = event.target.value === "en" ? "en" : "zh";
            i18n.changeLanguage(language);
            persistLanguage(language);
          }}
        >
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
      </header>
      <div className="tr-mobile-open-list">
        {pages.map((page) => (
          <a key={page.id} href={`/m/${page.id}`} className="tr-mobile-open-row">
            <span className="tr-mobile-open-icon"><PageIcon name={page.icon} /></span>
            <span>{t(`nav.${page.id}`, { defaultValue: page.title })}</span>
            <span className="tr-mobile-open-route">{page.route.split("?")[0]}</span>
          </a>
        ))}
      </div>
    </section>
  );
}
