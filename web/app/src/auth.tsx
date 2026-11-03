import {appEntrySearch} from "./app-route.ts";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Brand } from "./components/brand.tsx";
import { CloseOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { notify } from "./notifications/core.ts";
import { keycloakErrorKey, keycloakLoginAvailable } from "./auth-model.ts";
import { LocalResearchProvider } from "./local-research-context.tsx";

export type AuthSession = {
  username?: string;
  alias?: string;
  role?: string;
  capabilities?: Record<string, boolean>;
  admin_capabilities?: string[];
  public_server_login?: boolean;
  keycloak_roles?: string[];
  visitor_login?: boolean;
} | null;

type PublicEntry = {
  compliance_notice?: string;
  registration_notice?: string;
  public_compliance_information?: {
    service_operator?: string;
    icp_record?: string;
    security_record?: string;
    compliance_contact?: string;
    privacy_policy_url?: string;
  };
  public_registration_enabled?: boolean;
  require_device_auth?: boolean;
  public_server?: boolean;
  authentication_provider?: string;
};

type AuthContextValue = {
  session: AuthSession;
  logout: () => Promise<void>;
  openAuth: (mode:"login")=>void;
};

const AuthContext = createContext<AuthContextValue>({ session: null, logout: async () => undefined, openAuth:()=>undefined });

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

function notifyNative(action: "session-updated" | "logout"): void {
  const handler = (window as unknown as {
    webkit?: { messageHandlers?: { tradeResearchAuthentication?: { postMessage?: (value: { action: string }) => void } } };
  }).webkit?.messageHandlers?.tradeResearchAuthentication;
  handler?.postMessage?.({ action });
}

async function readJSON(response: Response): Promise<Record<string, any>> {
  try { return await response.json() as Record<string, any>; } catch { return {}; }
}

function currentPath(): string {
  return `${location.pathname}${appEntrySearch()}`;
}

export function AuthGate({ children, mobile = false }: { children: React.ReactNode; mobile?: boolean }): React.ReactElement {
  const {t}=useTranslation();
  const [dialogMode,setDialogMode]=useState<"login"|null>(null);
  const [session, setSession] = useState<AuthSession>(null);
  const [entry, setEntry] = useState<PublicEntry | null>(null);
  const [checking, setChecking] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    const query = new URLSearchParams(appEntrySearch());
    const error = history.state?.trAuthError || query.get("auth_error");
    if (!error) return;
    setAuthError(error);
    query.delete("auth_error");
    const search = query.toString();
    const state = {...history.state}; delete state.trAuthError;
    history.replaceState({...state,trEntrySearch:search ? `?${search}` : ""}, "", location.pathname === "/app" ? "/app" : `${location.pathname}${location.hash}`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/api/session", { credentials: "same-origin", cache: "no-store" }),
      fetch("/api/public/entry", { credentials: "same-origin", cache: "no-store" }),
    ]).then(async ([sessionResponse, entryResponse]) => {
      if (cancelled) return;
      const entryPayload = entryResponse.ok ? await readJSON(entryResponse) : {};
      setEntry(entryPayload as PublicEntry);
      if (sessionResponse.ok) {
        const value = await readJSON(sessionResponse);
        const restored = (value.session ?? value) as AuthSession;
        if (restored?.username && !restored.visitor_login) notifyNative("session-updated");
        setSession(restored);
      } else if (sessionResponse.status !== 401) {
        setUnavailable(true);
      }
    }).catch(() => { if (!cancelled) setUnavailable(true); })
      .finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, []);

  const logout = useCallback(async () => {
    try {
      const response=await fetch("/auth/logout", {method:"POST",credentials:"same-origin"});
      if(!response.ok && response.status!==401)throw new Error(t("auth.logoutFailed"));
      const value = await readJSON(response);
      notifyNative("logout");setSession(null);setDialogMode(null);
      if (typeof value.logout_url === "string" && value.logout_url) location.assign(value.logout_url);
    } catch {notify({code:"auth.logout.failed",type:"error",message:t("auth.logoutFailed")});}
  },[t]);
  const value = useMemo(() => ({session,logout,openAuth:setDialogMode}), [session,logout]);
  if(checking)return <div className="tr-auth-loading" role="status">{t("loading")}</div>;
  return <AuthContext.Provider value={value}>
    {session ? <div key={session.username||"session"} className="tr-authenticated-app" inert={Boolean(dialogMode)} aria-hidden={dialogMode?true:undefined}><LocalResearchProvider session={session} mobile={mobile}>{children}</LocalResearchProvider></div>:null}
    {!session || dialogMode ? <AuthOverlay key={dialogMode||"login"} entry={entry} unavailable={unavailable} authError={authError}
      onClose={session?()=>setDialogMode(null):undefined}/>:null}
  </AuthContext.Provider>;
}

export function AuthOverlay({ entry, unavailable, authError, onClose }: {
  onClose?:()=>void;
  entry: PublicEntry | null;
  unavailable: boolean;
  authError: string;
}): React.ReactElement {
  const { t } = useTranslation();
  const card=useRef<HTMLElement>(null);
  useEffect(()=>{
    const prior=document.activeElement as HTMLElement|null;
    const escape=(event:KeyboardEvent):void=>{
      if(event.key==='Escape'&&onClose){event.preventDefault();onClose();}
      if(event.key==='Tab'){
        const controls=[...(card.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),a[href],summary')||[])].filter(node=>node.getClientRects().length && (!node.closest("details:not([open])") || node.tagName==="SUMMARY"));
        const first=controls[0],last=controls.at(-1);
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',escape);
    return ()=>{document.removeEventListener('keydown',escape);queueMicrotask(()=>{if(prior?.isConnected)prior.focus();});};
  },[onClose]);
  const compliance = String(entry?.compliance_notice || "").trim()
    || t("auth.complianceFallback");
  const publicGate = Boolean(entry?.require_device_auth || entry?.public_server);
  const fullCompliance = `/compliance?next=${encodeURIComponent(currentPath())}`;
  const keycloakMode = keycloakLoginAvailable(entry);
  const startKeycloakLogin = (): void => {
    location.assign(`/auth/oidc/start?next=${encodeURIComponent(currentPath())}`);
  };
  const errorKey = keycloakErrorKey(authError);
  const keycloakErrorMessage = errorKey ? t(`auth.keycloakErrors.${errorKey}`) : "";

  return (
    <div className="tr-auth-overlay" role="dialog" aria-modal="true" aria-labelledby="tr-auth-title">
      <section ref={card} className="tr-auth-card">
        <header>
          {onClose?<button type="button" className="tr-auth-close" onClick={onClose} aria-label={t("close")}><CloseOutlined/></button>:null}
          <Brand />

          <h1 id="tr-auth-title">{t("auth.title")}</h1>
        </header>
        <div className="tr-auth-form">
          <button type="button" className="tr-auth-submit" disabled={!keycloakMode || unavailable} onClick={startKeycloakLogin}>{t("auth.keycloakSignIn")}</button>
          {publicGate?<a className="tr-auth-redirect" href={fullCompliance}>{t("auth.publicVisitorEntry")}</a>:null}
          {keycloakErrorMessage ? <p className="tr-auth-error" role="alert">{keycloakErrorMessage}</p> : null}
          {unavailable || !keycloakMode ? <div role="alert"><p className="tr-auth-error">{t("auth.unavailable")}</p><Button onClick={()=>location.reload()}>{t("retry")}</Button></div> : null}
        </div>
        <footer>
          <details className="tr-auth-access"><summary>{t("auth.accessInformation")}</summary>
            <p>{compliance}</p>
            {entry?.registration_notice?<p>{entry.registration_notice}</p>:null}
            {publicGate?<p>{t("auth.publicVisitorHint")}</p>:null}
            {publicGate?<dl className="tr-auth-public-compliance">
              <dt>{t("auth.serviceOperator")}</dt><dd>{entry?.public_compliance_information?.service_operator||t("auth.notConfigured")}</dd>
              <dt>{t("auth.filingInformation")}</dt><dd>{entry?.public_compliance_information?.icp_record||t("auth.notConfigured")}</dd>
              {entry?.public_compliance_information?.security_record?<><dt>{t("auth.securityFiling")}</dt><dd>{entry.public_compliance_information.security_record}</dd></>:null}
              {entry?.public_compliance_information?.compliance_contact?<><dt>{t("auth.complianceContact")}</dt><dd>{entry.public_compliance_information.compliance_contact}</dd></>:null}
              {entry?.public_compliance_information?.privacy_policy_url?<><dt>{t("auth.privacyPolicy")}</dt><dd><a href={entry.public_compliance_information.privacy_policy_url} rel="noopener noreferrer" target="_blank">{entry.public_compliance_information.privacy_policy_url}</a></dd></>:null}
            </dl>:null}
            <a href={fullCompliance}>{t("auth.openCompliance")}</a>
            <p>{t("auth.complianceFooter")}</p>
          </details>
        </footer>
      </section>
    </div>
  );
}
