import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Brand } from "./components/brand.tsx";

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
};

const AuthContext = createContext<AuthContextValue>({ session: null, logout: async () => undefined });

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
    try { await fetch("/auth/logout", { method: "POST", credentials: "same-origin" }); } catch { /* session is cleared locally regardless */ }
    notifyNative("logout");
    setSession(null);
  }, []);

  const value = useMemo(() => ({ session, logout }), [session, logout]);
  if (checking) return <div className="tr-auth-loading" role="status">…</div>;
  if (!session) {
    return <AuthOverlay entry={entry} unavailable={unavailable} onAuthenticated={(next) => {
      notifyNative("session-updated");
      setSession(next);
    }} />;
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function AuthOverlay({ entry, unavailable, onAuthenticated }: {
  entry: PublicEntry | null;
  unavailable: boolean;
  onAuthenticated: (session: AuthSession) => void;
}): React.ReactElement {
  const { t } = useTranslation();
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
    setRedirect("");
    setSubmitting(true);
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const value = await readJSON(response);
      if (!response.ok || !value.success) {
        const message = String(value.error || t("auth.loginFailed"));
        setError(message);
        if (value.redirect) setRedirect(String(value.redirect));
        return;
      }
      onAuthenticated(value as AuthSession);
    } catch {
      setError(t("auth.networkFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tr-auth-overlay" role="dialog" aria-modal="true" aria-labelledby="tr-auth-title">
      <section className="tr-auth-card">
        <header>
          <Brand />
          <span>{t("auth.eyebrow")}</span>
          <h1 id="tr-auth-title">{publicGate ? t("auth.publicTitle") : t("auth.title")}</h1>
          <p>{publicGate ? t("auth.publicHint") : t("auth.hint")}</p>
        </header>
        <div className="tr-auth-compliance" tabIndex={0} aria-label={t("auth.compliance")}>
          <p>{compliance}</p>
          {entry?.registration_notice ? <p>{entry.registration_notice}</p> : null}
        </div>
        <a className="tr-auth-compliance-link" href={fullCompliance}>{t("auth.openCompliance")}</a>
        <form className="tr-auth-form" onSubmit={submit}>
          <label>
            <span>{t("auth.username")}</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)}
              autoComplete="username" required disabled={submitting} />
          </label>
          <label>
            <span>{t("auth.password")}</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password" required disabled={submitting} />
          </label>
          <button type="submit" className="tr-auth-submit" disabled={submitting || !username || !password}>
            {submitting ? t("auth.signingIn") : t("auth.signIn")}
          </button>
          {error ? <p className="tr-auth-error" role="alert">{error}</p> : null}
          {redirect ? <a className="tr-auth-redirect" href={redirect}>{t("auth.guidedLogin")}</a> : null}
          {unavailable ? <p className="tr-auth-error" role="alert">{t("auth.unavailable")}</p> : null}
          {entry?.public_registration_enabled ? <a className="tr-auth-register" href="/login">{t("auth.register")}</a> : null}
        </form>
        <footer>{t("auth.complianceFooter")}</footer>
      </section>
    </div>
  );
}
