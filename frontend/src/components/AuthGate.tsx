import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";

type Session = { authenticated: boolean; configured: boolean };

function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => fetch("/api/auth/session").then((response) => response.json() as Promise<Session>).then(setSession).catch(() => setError("Could not reach the ClipforgeAI backend."));
  useEffect(() => { void refresh(); }, []);

  const login = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const body = new URLSearchParams({ password });
      const response = await fetch("/api/auth/login", { method: "POST", body });
      const result = await response.json() as { detail?: string; authenticated?: boolean };
      if (!response.ok) throw new Error(result.detail || "Sign-in failed.");
      setPassword(""); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Sign-in failed."); }
    finally { setBusy(false); }
  };

  if (!session) return <main className="login-page"><section className="login-card"><h1>Clipforge<span>AI</span></h1><p>Connecting to your workspace…</p></section></main>;
  if (!session.configured) return <main className="login-page"><section className="login-card"><h1>Secure your workspace</h1><p>Set <code>APP_PASSWORD</code> and a unique <code>APP_SESSION_SECRET</code> in the backend environment before using this publicly hosted site.</p></section></main>;
  if (!session.authenticated) return <main className="login-page"><form className="login-card" onSubmit={(event) => void login(event)}><h1>Clipforge<span>AI</span></h1><p>Sign in to your private workspace.</p><label>Workspace password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label><button className="primary-button" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>{error && <p className="project-error" role="alert">{error}</p>}</form></main>;
  return <>{children}</>;
}

export default AuthGate;
