import React, { useEffect, useState } from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { LanguageSwitch } from "./language-switch.tsx";
import { PageIcon } from "../icon.tsx";

const SECTIONS = [
  { id: "account", icon: "account" },
  { id: "server", icon: "catalog" },
  { id: "federation", icon: "workspace" },
  { id: "controlDatabase", icon: "runs" },
  { id: "devices", icon: "trading" },
  { id: "quota", icon: "research" },
  { id: "workspace", icon: "workspace" },
  { id: "language", icon: "research" },
  { id: "updates", icon: "runs" },
  { id: "manager", icon: "runs" },
  { id: "docs", icon: "research" },
  { id: "profiles", icon: "account" },
] as const;

export function SettingsOverlay({
  open, onClose, onResetLayout,
}: {
  open: boolean;
  onClose: () => void;
  onResetLayout: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const [section, setSection] = useState<string>("account");
  const [session, setSession] = useState<{ username?: string; role?: string; capabilities?: { manager?: boolean } } | null>(null);
  const [serverInfo, setServerInfo] = useState<Record<string, unknown> | null>(null);
  const [sectionData, setSectionData] = useState<Record<string, unknown> | null>(null);
  const [docPage, setDocPage] = useState<string>("");
  const [docContent, setDocContent] = useState<string>("");
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetch("/api/session", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : null)
      .then((value) => { if (!cancelled) setSession(value?.session ?? value ?? null); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [open]);
  useEffect(() => {
    const endpoints: Record<string, string> = {
      controlDatabase: "/api/control-database/config",
      manager: "/api/worktrees",
      docs: "/api/docs/index",
      profiles: "/api/client/profiles",
      federation: "/api/federation/config",
      devices: "/api/devices",
      quota: "/api/jobs/storage",
      updates: "/api/client/releases/beta.json",
    };
    const endpoint = endpoints[section];
    if (!open || !endpoint) { setSectionData(null); return; }
    fetch(endpoint, { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : null)
      .then((value) => setSectionData(value))
      .catch(() => setSectionData(null));
  }, [open, section]);

  useEffect(() => {
    if (!open || section !== "docs" || !docPage) { setDocContent(""); return; }
    fetch(`/api/docs/pages/${encodeURIComponent(docPage)}`, { credentials: "same-origin" })
      .then((response) => response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => setDocContent(value))
      .catch(() => setDocContent(""));
  }, [open, section, docPage]);

  useEffect(() => {
    if (!open || section !== "server") return;
    fetch("/api/server/network-info", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : null)
      .then((value) => setServerInfo(value))
      .catch(() => setServerInfo(null));
  }, [open, section]);
  const visibleSections = SECTIONS.filter((item) => item.id !== "manager" || Boolean(session?.capabilities?.manager));
  const current = visibleSections.find((item) => item.id === section) ?? visibleSections[0];
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      centered
      width={820}
      className="tr-settings-overlay"
      destroyOnClose
      title={null}
    >
      <div className="tr-settings-hub">
        <nav className="tr-settings-nav" aria-label={t("settingsPanel.title")}>
          {visibleSections.map((item) => (
            <button
              key={item.id}
              type="button"
              className={section === item.id ? "is-active" : ""}
              onClick={() => setSection(item.id)}
            >
              <PageIcon name={item.icon} />
              <span>{t(`settingsPanel.sections.${item.id}`)}</span>
            </button>
          ))}
        </nav>
        <section className="tr-settings-content">
          <header className="tr-settings-page-header">
            <span className="tr-settings-page-icon"><PageIcon name={current.icon} /></span>
            <div>
              <h2>{t(`settingsPanel.sections.${current.id}`)}</h2>
              <p>{t(`settingsPanel.descriptions.${current.id}`)}</p>
            </div>
          </header>
          {current.id === "language" ? (
            <div className="tr-settings-card">
              <h3>{t("settingsPanel.language")}</h3>
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.language")}</b><small>{t("settingsPanel.languageHint")}</small></div>
                <LanguageSwitch />
              </div>
            </div>
          ) : current.id === "workspace" ? (
            <div className="tr-settings-card">
              <h3>{t("settingsPanel.layout")}</h3>
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.layout")}</b><small>{t("settingsPanel.layoutHint")}</small></div>
                <button type="button" className="tr-toolbar-button" onClick={onResetLayout}>{t("resetLayout")}</button>
              </div>
            </div>
          ) : current.id === "server" ? (
            <div className="tr-settings-card">
              <h3>{t("settingsPanel.sections.server")}</h3>
              {serverInfo ? <pre className="tr-job-detail">{JSON.stringify(serverInfo, null, 2)}</pre> : <p>{t("loading")}</p>}
            </div>
          ) : current.id === "docs" ? (
            <div className="tr-settings-card">
              <h3>{t("settingsPanel.sections.docs")}</h3>
              {sectionData ? (
                <div className="tr-doc-pages">
                  {((sectionData.pages ?? sectionData.items ?? []) as Record<string, unknown>[]).map((doc, index) => {
                    const slug = String(doc.slug ?? doc.path ?? doc.id ?? index);
                    return <button key={slug} type="button" className={docPage === slug ? "is-active" : ""} onClick={() => setDocPage(slug)}>{String(doc.title ?? doc.name ?? slug)}</button>;
                  })}
                </div>
              ) : <p>{t("loading")}</p>}
              {docPage ? <pre className="tr-job-detail">{docContent || t("loading")}</pre> : null}
            </div>
          ) : ["controlDatabase", "federation", "devices", "quota", "updates", "manager", "profiles"].includes(current.id) ? (
            <div className="tr-settings-card">
              <h3>{t(`settingsPanel.sections.${current.id}`)}</h3>
              {sectionData ? <pre className="tr-job-detail">{JSON.stringify(sectionData, null, 2)}</pre> : <p>{t("loading")}</p>}
            </div>
          ) : current.id === "account" ? (
            <div className="tr-settings-card">
              <h3>{t("settingsPanel.sections.account")}</h3>
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.accountSession")}</b><small>{t("settingsPanel.accountHint")}</small></div>
                <span className="tr-settings-value">{session?.username || t("settingsPanel.notSignedIn")}</span>
              </div>
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.role")}</b><small>{t("settingsPanel.roleHint")}</small></div>
                <span className="tr-settings-value">{session?.role || "—"}</span>
              </div>
            </div>
          ) : (
            <div className="tr-settings-card tr-settings-migrating">
              <h3>{t(`settingsPanel.sections.${current.id}`)}</h3>
              <p>{t("settingsPanel.migrating")}</p>
            </div>
          )}
        </section>
      </div>
    </Modal>
  );
}
