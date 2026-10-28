import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Brand } from "./components/brand.tsx";
import { CloseOutlined } from "@ant-design/icons";
import { loadScript } from "./assets.ts";
import { request } from "./configuration/api.ts";
import { notify } from "./notifications/core.ts";

export type AuthSession = {
  username?: string;
  alias?: string;
  role?: string;
  capabilities?: Record<string, boolean>;
  visitor_login?: boolean;
} | null;

type PublicEntry = {
  compliance_notice?: string;
  registration_notice?: string;
  public_registration_enabled?: boolean;
  require_device_auth?: boolean;
  public_server?: boolean;
};

type AuthContextValue = {
  session: AuthSession;
  logout: () => Promise<void>;
  openAuth: (mode:"login"|"register")=>void;
  registrationEnabled:boolean;
};

const AuthContext = createContext<AuthContextValue>({ session: null, logout: async () => undefined, openAuth:()=>undefined, registrationEnabled:false });

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

function notifyNative(action: "session-updated" | "logout"): void {
  const handler = (window as unknown as {
    webkit?: { messageHandlers?: { factorTesterAuthentication?: { postMessage?: (value: { action: string }) => void } } };
  }).webkit?.messageHandlers?.factorTesterAuthentication;
  handler?.postMessage?.({ action });
}

async function readJSON(response: Response): Promise<Record<string, any>> {
  try { return await response.json() as Record<string, any>; } catch { return {}; }
}

function currentPath(): string {
  return `${location.pathname}${location.search}`;
}

export function AuthGate({ children }: { children: React.ReactNode }): React.ReactElement {
  const {t}=useTranslation();
  const [dialogMode,setDialogMode]=useState<"login"|"register"|null>(null);
  const [session, setSession] = useState<AuthSession>(null);
  const [entry, setEntry] = useState<PublicEntry | null>(null);
  const [checking, setChecking] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

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
        setSession((value.session ?? value) as AuthSession);
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
      notifyNative("logout");setSession(null);setDialogMode(null);
    } catch {notify({code:"auth.logout.failed",type:"error",message:t("auth.logoutFailed")});}
  },[t]);
  const value = useMemo(() => ({session,logout,openAuth:setDialogMode,registrationEnabled:Boolean(entry?.public_registration_enabled)}), [session,logout,entry]);
  const authenticated=(next:AuthSession):void=>{notifyNative("session-updated");setSession(next);setDialogMode(null);};
  if(checking)return <div className="tr-auth-loading" role="status">{t("loading")}</div>;
  return <AuthContext.Provider value={value}>
    {session ? <div key={session.username||"session"} className="tr-authenticated-app" inert={Boolean(dialogMode)} aria-hidden={dialogMode?true:undefined}>{children}</div>:null}
    {!session || dialogMode ? <AuthOverlay key={dialogMode||"login"} mode={dialogMode||"login"} entry={entry} unavailable={unavailable}
      onClose={session?()=>setDialogMode(null):undefined} onAuthenticated={authenticated}/>:null}
  </AuthContext.Provider>;
}

function AuthOverlay({ entry, unavailable, onAuthenticated, mode:initialMode, onClose }: {
  mode:"login"|"register"; onClose?:()=>void;
  entry: PublicEntry | null;
  unavailable: boolean;
  onAuthenticated: (session: AuthSession) => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const [mode,setMode]=useState(initialMode);
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
  const [organization,setOrganization]=useState("");
  const [confirmation,setConfirmation]=useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [redirect, setRedirect] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const compliance = String(entry?.compliance_notice || "").trim()
    || t("auth.complianceFallback");
  const publicGate = Boolean(entry?.require_device_auth || entry?.public_server);
  const fullCompliance = `/compliance?next=${encodeURIComponent(currentPath())}`;

  const submit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError("");
    if(mode==="register" && password!==confirmation){setError(t("auth.passwordMismatch"));return;}
    if(mode==="register" && !entry?.public_registration_enabled)return;
    setRedirect("");
    setSubmitting(true);
    try {
      const response = await fetch(mode==="register"?"/auth/register":"/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password, ...(mode==="register"?{organization_id:organization}:{}) }),
      });
      const value = await readJSON(response);
      if (!response.ok || !value.success) {
        const message = String(value.error || t("auth.loginFailed"));
        setError(message);
        if (value.redirect) setRedirect(String(value.redirect));
        return;
      }
      const {username:principal,alias,role,capabilities,visitor_login}=value;
      if(visitor_login){
        try {
          await loadScript("/research-static/app/visitor-device.js");
          const devices=(window as Window & {FTVisitorDevice?:{ensureForSession:(context:{api:typeof request},session:AuthSession)=>Promise<unknown>}}).FTVisitorDevice;
          if(!devices)throw new Error("Device enrollment unavailable");
          await devices.ensureForSession({api:request},{username:principal,visitor_login});
        } catch {notify({code:"auth.device.failed",type:"error",message:t("auth.deviceEnrollmentFailed")});}
      }
      onAuthenticated({username:principal,alias,role,capabilities,visitor_login});
    } catch {
      setError(t("auth.networkFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tr-auth-overlay" role="dialog" aria-modal="true" aria-labelledby="tr-auth-title">
      <section ref={card} className="tr-auth-card">
        <header>
          {onClose?<button type="button" className="tr-auth-close" onClick={onClose} aria-label={t("close")}><CloseOutlined/></button>:null}
          <Brand />

          <h1 id="tr-auth-title">{mode==="register"?t("auth.register"):t("auth.title")}</h1>
          <p>{mode==="register"?t("auth.registerHint"):t("auth.hint")}</p>
        </header>
        <nav className="tr-auth-switch" aria-label={t("auth.account")}>
          <button type="button" aria-pressed={mode==="login"} onClick={()=>{setMode("login");setError("");}}>{t("auth.signIn")}</button>
          <button type="button" aria-pressed={mode==="register"} onClick={()=>{setMode("register");setError("");}}>{t("auth.register")}</button>
        </nav>
        {mode==="register"&&!entry?.public_registration_enabled?<p role="status">{entry?.registration_notice||t("auth.registrationClosed")}</p>:<form className="tr-auth-form" onSubmit={submit}>
          <label>
            <span>{t("auth.username")}</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)}
              autoComplete="username" autoFocus required maxLength={mode === "register" ? 32 : undefined} disabled={submitting} />
          </label>
          {mode === "register" ? <small className="tr-auth-alias-hint">{t("auth.aliasHint")}</small> : null}
          <label>
            <span>{t("auth.password")}</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)}
              autoComplete={mode==="register"?"new-password":"current-password"} required disabled={submitting} />
          </label>
          {mode==="register"?<>
            <label><span>{t("auth.confirmPassword")}</span><input type="password" autoComplete="new-password" required value={confirmation} onChange={event=>setConfirmation(event.target.value)} disabled={submitting}/></label>
            <label><span>{t("auth.organization")}</span><input value={organization} onChange={event=>setOrganization(event.target.value)} disabled={submitting}/></label>
          </>:null}
          <button type="submit" className="tr-auth-submit" disabled={submitting || !username || !password}>
            {submitting ? t(mode==="register"?"auth.registering":"auth.signingIn") : t(mode==="register"?"auth.register":"auth.signIn")}
          </button>
          {error ? <p className="tr-auth-error" role="alert">{error}</p> : null}
          {redirect ? <a className="tr-auth-redirect" href={redirect}>{t("auth.guidedLogin")}</a> : null}
          {unavailable ? <p className="tr-auth-error" role="alert">{t("auth.unavailable")}</p> : null}
        </form>}
        <footer>
          <span>{t("auth.managedAccess")}</span>
          <details className="tr-auth-access"><summary>{t("auth.accessInformation")}</summary>
            <p>{compliance}</p>
            {entry?.registration_notice?<p>{entry.registration_notice}</p>:null}
            {publicGate?<p>{t("auth.publicVisitorHint")}</p>:null}
            <a href={fullCompliance}>{t("auth.openCompliance")}</a>
            <p>{t("auth.complianceFooter")}</p>
          </details>
        </footer>
      </section>
    </div>
  );
}
