import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Spin } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { loadScript } from "../assets.ts";
import { agentProfileLabel, agentRuntimeAvailability, isUnboundAgentRuntimeError, selfAgentProfile, type AgentProfile } from "../agent-assistant-model.ts";

type LegacyChatRoot = HTMLElement & { __ftBeforeTabSave?: () => void };
type LegacyChatHost = HTMLElement & { __ftBeforeTabSave?: () => void };
type LegacyWindow = Window & {
  FTStaticLoader?: { loadGroups: (groups: string[]) => Promise<unknown> };
  FTI18n?: { t?: (key: string, fallback?: string) => string };
  FTAgentChat?: { render: (context: Record<string, unknown>, profile: AgentProfile, options: Record<string, unknown>) => Promise<LegacyChatRoot> };
};

type AgentAssistantProps = {
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  presentation?: "drawer" | "panel";
};

export function AgentAssistant({ open, onOpenChange, presentation = "drawer" }: AgentAssistantProps): React.ReactElement {
  const { t, i18n } = useTranslation();
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [setupRequired, setSetupRequired] = useState<"unbound" | "server-required" | "" >("");
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const mountRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<LegacyChatRoot | null>(null);
  const pendingRef = useRef<Promise<void> | null>(null);
  const startedHereRef = useRef(false);
  const startedProfileRef = useRef("");
  const profileRef = useRef<AgentProfile | null>(null);
  profileRef.current = profile;
  const ownerRef = useRef(`react-agent-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`);
  const aliveRef = useRef(true);
  const legacyRef = useRef(window as LegacyWindow);
  const compact = useCompactLayout();

  const disposeChat = useCallback(() => {
    const root = rootRef.current;
    root?.querySelector<LegacyChatHost>(".profile-chatkit-host")?.__ftBeforeTabSave?.();
    root?.remove();
    rootRef.current = null;
  }, []);

  const loadAssistant = useCallback((): Promise<void> => {
    if (pendingRef.current) return pendingRef.current;
    setLoading(true);
    setError("");
    setSetupRequired("");
    pendingRef.current = (async () => {
      const profilesPayload = await request("/api/client/profiles");
      const self = selfAgentProfile(profilesPayload.profiles);
      if (!self) throw new Error(t("assistant.noProfile"));
      const availability = agentRuntimeAvailability(self);
      if (availability === "server-required" || availability === "unbound") {
        setSetupRequired(availability);
        return;
      }
      if (!mountRef.current) throw new Error(t("assistant.mountUnavailable"));

      if (!legacyRef.current.FTStaticLoader?.loadGroups) await loadScript("/research-static/core/module-loader.js");
      if (!legacyRef.current.FTStaticLoader?.loadGroups) throw new Error(t("assistant.loaderUnavailable"));
      await legacyRef.current.FTStaticLoader.loadGroups(["profile-agent-chat"]);
      if (!legacyRef.current.FTAgentChat?.render) throw new Error(t("assistant.chatUnavailable"));
      const statusPayload = await request(`/api/client/profile-agent?profile_id=${encodeURIComponent(self.profile_id)}`);
      let status = statusPayload.status || {};
      if (!status.running) {
        const started = await request("/api/client/profile-agent/start", {
          method: "POST", body: JSON.stringify({ profile_id: self.profile_id }),
        });
        status = started.status || status;
        startedHereRef.current = true;
        startedProfileRef.current = self.profile_id;
      }
      if (!aliveRef.current || !mountRef.current) return;

      const legacyT = (key: string): string => {
        const translated = legacyRef.current.FTI18n?.t?.(key, key);
        return translated && translated !== key ? translated : t(key, { defaultValue: key });
      };
      const context: Record<string, unknown> = {
        api: request,
        t: legacyT,
        locale: i18n.language === "zh" ? "zh-Hans" : i18n.language,
        language: i18n.language,
        lang: i18n.language,
        tabID: ownerRef.current,
        isRouteCurrent: () => aliveRef.current,
        navigate: (path: string) => { window.location.assign(path); },
      };
      const chat = await legacyRef.current.FTAgentChat.render(context, self, {
        conversationOnly: true,
        lifecycleManaged: true,
        runtimeStatus: status,
        mountHost: mountRef.current,
      });
      if (!aliveRef.current) {
        chat.querySelector<LegacyChatHost>(".profile-chatkit-host")?.__ftBeforeTabSave?.();
        chat.remove();
        return;
      }
      rootRef.current = chat;
      setProfile(self);
    })().catch((cause: unknown) => {
      const message = cause instanceof Error ? cause.message : String(cause);
      if (aliveRef.current && isUnboundAgentRuntimeError(message)) setSetupRequired("unbound");
      else if (aliveRef.current) setError(message);
      pendingRef.current = null;
    }).finally(() => {
      if (aliveRef.current) setLoading(false);
    });
    return pendingRef.current;
  }, [i18n.language, t]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      disposeChat();
      const profileID = startedProfileRef.current || profileRef.current?.profile_id;
      if (startedHereRef.current && profileID) {
        void request("/api/client/profile-agent/stop", {
          method: "POST", body: JSON.stringify({ profile_id: profileID }),
        }).catch(() => undefined);
      }
    };
  }, [disposeChat]);

  useEffect(() => {
    if (open && !rootRef.current) void loadAssistant();
  }, [loadAssistant, open, retry]);

  const retryLoad = (): void => { pendingRef.current = null; setRetry((value) => value + 1); };
  const width = compact ? "100vw" : 560;
  const content = <>
    {setupRequired ? <div className="tr-agent-assistant-error"><Alert type="warning" showIcon message={t(setupRequired === "unbound" ? "assistant.runtimeUnbound" : "assistant.serverRuntimeRequired")} description={t("assistant.runtimeSetupHint")} /><div className="tr-agent-assistant-setup-actions"><Button size="small" onClick={() => window.location.assign("/research?section=profiles")}>{t("assistant.openProfileSettings")}</Button></div></div> : null}
    {error ? <div className="tr-agent-assistant-error"><Alert type="error" showIcon message={t("assistant.loadFailed")} description={error} action={<Button size="small" icon={<ReloadOutlined />} onClick={retryLoad}>{t("assistant.retry")}</Button>} /></div> : null}
    {!rootRef.current && !error && !setupRequired ? <div className="tr-agent-assistant-loading" role="status"><Spin size="small" />{loading ? t("assistant.loading") : t("assistant.openHint")}</div> : null}
    <div className="tr-agent-assistant-mount" ref={mountRef} />
  </>;

  if (presentation === "panel") {
    return <section className="tr-agent-assistant-panel" aria-label={t("assistant.title")}>{content}</section>;
  }

  return <>
    <Drawer
      className="tr-agent-assistant-drawer"
      title={<div className="tr-agent-assistant-title"><strong>{t("assistant.title")}</strong>{profile ? <span>{agentProfileLabel(profile)}</span> : null}</div>}
      placement="right"
      width={width}
      open={open}
      onClose={() => onOpenChange?.(false)}
      destroyOnHidden={false}
    >
      {content}
    </Drawer>
  </>;
}
