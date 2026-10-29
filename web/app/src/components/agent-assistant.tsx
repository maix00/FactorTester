import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Select, Spin, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { loadScript } from "../assets.ts";
import { agentAssistantSetupStep, agentProfileLabel, isUnboundAgentRuntimeError, selfAgentProfile, type AgentProfile } from "../agent-assistant-model.ts";
import { AgentModelSetupModal } from "./agent-model-setup-modal.tsx";

type LegacyChatRoot = HTMLElement & { __ftBeforeTabSave?: () => void };
type LegacyChatHost = HTMLElement & { __ftBeforeTabSave?: () => void };
type LegacyWindow = Window & {
  FTStaticLoader?: { loadGroups: (groups: string[]) => Promise<unknown> };
  FTI18n?: { t?: (key: string, fallback?: string) => string };
  FTAgentChat?: { render: (context: Record<string, unknown>, profile: AgentProfile, options: Record<string, unknown>) => Promise<LegacyChatRoot> };
};

type AgentModelProvider = {
  provider_id: string;
  label: string;
  default_model: string;
};
type AgentRuntimeCapability = {
  runtime: string;
  executable_label?: string;
  protocols?: string[];
  protocol_details?: Array<{ protocol: string; label?: string }>;
  network_route_details?: Array<{ network_route: string; label: string }>;
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
  const [setupRequired, setSetupRequired] = useState<"unbound" | "server-required" | "claim" | "" >("");
  const [providers, setProviders] = useState<AgentModelProvider[]>([]);
  const [runtimeCapabilities, setRuntimeCapabilities] = useState<AgentRuntimeCapability[]>([]);
  const [providerID, setProviderID] = useState("");
  const [setupBusy, setSetupBusy] = useState(false);
  const [setupError, setSetupError] = useState("");
  const [modelSetupOpen, setModelSetupOpen] = useState(false);
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

  const loadProviders = useCallback(async (preferredProviderID = ""): Promise<void> => {
    setSetupError("");
    try {
      const value = await request("/api/client/agent-models?runtime_kind=server");
      const nextProviders = Array.isArray(value.providers) ? value.providers as AgentModelProvider[] : [];
      setRuntimeCapabilities(Array.isArray(value.runtime_capabilities) ? value.runtime_capabilities as AgentRuntimeCapability[] : []);
      setProviders(nextProviders);
      setProviderID((current) => [preferredProviderID, current].find((candidate) =>
        candidate && nextProviders.some((item) => item.provider_id === candidate)) || nextProviders[0]?.provider_id || "");
    } catch (cause) {
      setProviders([]);
      setRuntimeCapabilities([]);
      setProviderID("");
      setSetupError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  const refreshSelfProfile = useCallback(async (): Promise<AgentProfile> => {
    const profilesPayload = await request("/api/client/profiles");
    const self = selfAgentProfile(profilesPayload.profiles);
    if (!self) throw new Error(t("assistant.noProfile"));
    setProfile(self);
    return self;
  }, [t]);

  const continueAfterSetup = useCallback((nextStep: "claim" | ""): void => {
    setSetupError("");
    setSetupRequired(nextStep);
    pendingRef.current = null;
    setRetry((value) => value + 1);
  }, []);

  const bindServerRuntime = useCallback(async (): Promise<void> => {
    const current = profileRef.current;
    if (!current || setupBusy) return;
    setSetupBusy(true);
    setSetupError("");
    try {
      await request("/api/client/profile-runtime", {
        method: "POST",
        body: JSON.stringify({ profile_id: current.profile_id, runtime_kind: "server", executor_id: "" }),
      });
      const updated = await refreshSelfProfile();
      await loadProviders();
      continueAfterSetup(updated.active_claim ? "" : "claim");
    } catch (cause) {
      setSetupError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSetupBusy(false);
    }
  }, [continueAfterSetup, loadProviders, refreshSelfProfile, setupBusy]);

  const claimAgent = useCallback(async (): Promise<void> => {
    const current = profileRef.current;
    if (!current || !providerID || setupBusy) return;
    setSetupBusy(true);
    setSetupError("");
    try {
      await request("/api/client/profile-claims", {
        method: "POST",
        body: JSON.stringify({ profile_id: current.profile_id, provider_id: providerID }),
      });
      await refreshSelfProfile();
      continueAfterSetup("");
    } catch (cause) {
      setSetupError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSetupBusy(false);
    }
  }, [continueAfterSetup, providerID, refreshSelfProfile, setupBusy]);

  const loadAssistant = useCallback((): Promise<void> => {
    if (pendingRef.current) return pendingRef.current;
    setLoading(true);
    setError("");
    setSetupRequired("");
    pendingRef.current = (async () => {
      const profilesPayload = await request("/api/client/profiles");
      const self = selfAgentProfile(profilesPayload.profiles);
      if (!self) throw new Error(t("assistant.noProfile"));
      setProfile(self);
      const setupStep = agentAssistantSetupStep(self);
      if (setupStep === "client-runtime") {
        setSetupRequired("server-required");
        return;
      }
      if (setupStep === "bind-server") {
        setSetupRequired("unbound");
        await loadProviders();
        return;
      }
      if (setupStep === "claim-agent") {
        setSetupRequired("claim");
        await loadProviders();
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
  }, [i18n.language, loadProviders, t]);

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
    {setupRequired === "server-required" ? <div className="tr-agent-assistant-setup">
      <Alert type="info" showIcon message={t("assistant.clientRuntimeTitle")} description={t("assistant.clientRuntimeHint")} />
      {profile && !profile.active_claim ? <Button loading={setupBusy} onClick={() => void bindServerRuntime()}>{t("assistant.switchToServerRuntime")}</Button> : null}
      {profile?.active_claim ? <Typography.Text type="secondary">{t("assistant.releaseClientClaimFirst")}</Typography.Text> : null}
      {setupError ? <Alert type="error" showIcon message={setupError} /> : null}
    </div> : null}
    {setupRequired === "unbound" ? <div className="tr-agent-assistant-setup">
      <Typography.Text type="secondary">{t("assistant.runtimeSetupHint")}</Typography.Text>
      <div className="tr-agent-assistant-setup-step"><span className="tr-agent-assistant-step-number">1</span><div><strong>{t("assistant.bindRuntimeTitle")}</strong><Typography.Paragraph type="secondary">{t("assistant.bindRuntimeHint")}</Typography.Paragraph></div></div>
      <Button type="primary" loading={setupBusy} onClick={() => void bindServerRuntime()}>{t("assistant.bindRuntime")}</Button>
      {setupError ? <Alert type="error" showIcon message={setupError} /> : null}
    </div> : null}
    {setupRequired === "claim" ? <div className="tr-agent-assistant-setup">
      <div className="tr-agent-assistant-setup-step"><span className="tr-agent-assistant-step-number">2</span><div><strong>{t("assistant.claimAgentTitle")}</strong><Typography.Paragraph type="secondary">{t("assistant.claimAgentHint")}</Typography.Paragraph></div></div>
      {providers.length ? <>
        <label className="tr-agent-assistant-provider-label" htmlFor="tr-agent-assistant-provider">{t("assistant.modelProvider")}</label>
        <Select id="tr-agent-assistant-provider" value={providerID || undefined} onChange={setProviderID} options={providers.map((item) => ({ value: item.provider_id, label: `${item.label} · ${item.default_model}` }))} />
        <div className="tr-agent-assistant-provider-actions">
          <Button type="primary" loading={setupBusy} disabled={!providerID} onClick={() => void claimAgent()}>{t("assistant.claimAgent")}</Button>
          <Button disabled={setupBusy || !runtimeCapabilities.length} onClick={() => setModelSetupOpen(true)}>{t("assistant.addModelProvider")}</Button>
        </div>
      </> : <>
        <Typography.Paragraph type="secondary">{setupError || t("assistant.noServerProvider")}</Typography.Paragraph>
        <div className="tr-agent-assistant-setup-actions"><Button type="primary" disabled={!runtimeCapabilities.length} onClick={() => setModelSetupOpen(true)}>{t("assistant.addModelProvider")}</Button><Button size="small" onClick={() => void loadProviders()}>{t("assistant.refreshProviders")}</Button></div>
      </>}
      {setupError && providers.length ? <Alert type="error" showIcon message={setupError} /> : null}
    </div> : null}
    {error ? <div className="tr-agent-assistant-error"><Alert type="error" showIcon message={t("assistant.loadFailed")} description={error} action={<Button size="small" icon={<ReloadOutlined />} onClick={retryLoad}>{t("assistant.retry")}</Button>} /></div> : null}
    {!rootRef.current && !error && !setupRequired ? <div className="tr-agent-assistant-loading" role="status"><Spin size="small" />{loading ? t("assistant.loading") : t("assistant.openHint")}</div> : null}
    <div className="tr-agent-assistant-mount" ref={mountRef} />
    <AgentModelSetupModal
      open={modelSetupOpen}
      onCancel={() => setModelSetupOpen(false)}
      capabilities={runtimeCapabilities}
      onSaved={(id) => { setModelSetupOpen(false); void loadProviders(id); }}
    />
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
