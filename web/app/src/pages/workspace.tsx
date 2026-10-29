import React from "react";
import { pagesForAdminCapabilities } from "../registry.ts";
import { useTranslation } from "react-i18next";
import { usePageInstance } from "../page-instance.ts";
import { AccountMenu } from "../components/account-actions.tsx";
import { PageIcon } from "../icon.tsx";
import { useAuth } from "../auth.tsx";

const RECENT_KEY = "tr.mobile.recent";

function recentIds(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function WorkspacePage({ onOpen }: { onOpen?: (id: string) => void }): React.ReactElement {
  const { t } = useTranslation();
  const instance = usePageInstance();
  const { session } = useAuth();
  const recent = recentIds();
  const pages = pagesForAdminCapabilities("mobile", session?.admin_capabilities || [])
    .filter((page) => !page.mobileTab && (page.sidebarVisible !== false || page.id === "settings"))
    .sort((a, b) => {
      const ai = recent.indexOf(a.id);
      const bi = recent.indexOf(b.id);
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
    });
  return (
    <section className="tr-mobile-workspace">
      <header className="tr-mobile-workspace-header">
        <AccountMenu/>
      </header>
      <div className="tr-mobile-open-list">
        {pages.map((page) => (
          <button key={page.id} type="button" className="tr-mobile-open-row" onClick={() => onOpen ? onOpen(page.id) : instance.open(page.id)}>
            <span className="tr-mobile-open-icon"><PageIcon name={page.icon} /></span>
            <span>{t(`nav.${page.id}`, { defaultValue: page.title })}</span>
            <span aria-hidden="true">›</span>
          </button>
        ))}
      </div>
    </section>
  );
}
