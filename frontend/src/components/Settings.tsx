import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

type Provider = "youtube" | "instagram" | "tiktok" | "facebook" | "x" | "linkedin";
type Account = { provider: Provider; id: string; name: string; connected_at: string };
type ScheduledPost = { id: string; project_id: string; clip_number: number; provider: Provider; account_id: string; caption: string; scheduled_at: string; status: string; error?: string | null; remote_url?: string | null };
const providers: { id: Provider; label: string; mark: string; note: string }[] = [
  { id: "youtube", label: "YouTube Shorts", mark: "▶", note: "Google OAuth and YouTube Data API upload permission" },
  { id: "instagram", label: "Instagram Reels", mark: "◎", note: "Professional Instagram account connected to a Facebook Page" },
  { id: "tiktok", label: "TikTok", mark: "♪", note: "Content Posting API, approved video.publish scope, and app audit for public posts" },
  { id: "facebook", label: "Facebook Reels", mark: "f", note: "Facebook Page with video publishing permissions" },
  { id: "x", label: "X", mark: "𝕏", note: "X API OAuth 2.0 with media.write and tweet.write access" },
  { id: "linkedin", label: "LinkedIn", mark: "in", note: "LinkedIn OAuth and w_member_social permission" },
];

function Settings() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [ready, setReady] = useState<Record<string, boolean>>({});
  const [error, setError] = useState(() => new URLSearchParams(window.location.search).has("connect_error") ? `Could not connect ${new URLSearchParams(window.location.search).get("connect_error")}. Check the provider app configuration and permissions.` : "");
  const [notice, setNotice] = useState(() => new URLSearchParams(window.location.search).has("connected") ? `${new URLSearchParams(window.location.search).get("connected")} account connected. Select the intended account below.` : "");
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const reload = async () => {
    const [accountResponse, capabilityResponse] = await Promise.all([fetch("/api/social/accounts"), fetch("/api/capabilities")]);
    if (!accountResponse.ok || !capabilityResponse.ok) throw new Error("Could not load provider connections.");
    const data = await capabilityResponse.json() as { social_configured: Record<string, boolean> };
    setAccounts(await accountResponse.json() as Account[]); setReady(data.social_configured || {});
  };
  useEffect(() => {
    const load = async () => {
      try {
        const [accountResponse, capabilityResponse] = await Promise.all([fetch("/api/social/accounts"), fetch("/api/capabilities")]);
        if (!accountResponse.ok || !capabilityResponse.ok) throw new Error("Could not load provider connections.");
        const data = await capabilityResponse.json() as { social_configured: Record<string, boolean> };
        setAccounts(await accountResponse.json() as Account[]); setReady(data.social_configured || {});
        const queueResponse = await fetch("/api/scheduled-posts");
        if (queueResponse.ok) setPosts(await queueResponse.json() as ScheduledPost[]);
      } catch (e) { setError(e instanceof Error ? e.message : "Could not load accounts."); }
    };
    void load();
    const params = new URLSearchParams(window.location.search);
    if (params.has("connected") || params.has("connect_error")) window.history.replaceState({}, "", "/settings");
  }, []);
  const disconnect = async (account: Account) => {
    const response = await fetch(`/api/social/${account.provider}/accounts/${encodeURIComponent(account.id)}`, { method: "DELETE" });
    if (!response.ok) { setError("Could not disconnect this account."); return; }
    await reload(); setNotice(`${account.name} disconnected.`);
  };
  const cancelPost = async (post: ScheduledPost) => {
    const response = await fetch(`/api/scheduled-posts/${post.id}`, { method: "DELETE" });
    if (!response.ok) { setError("This post can no longer be cancelled."); return; }
    setPosts((current) => current.filter((item) => item.id !== post.id));
  };

  return <main className="settings-page"><div className="settings-content"><Link className="back-link" to="/">← Back to dashboard</Link><header className="new-project-header"><p className="eyebrow">PUBLISHING SETUP</p><h1>Connected accounts</h1><p>Connect the channels you want to publish to. Tokens are encrypted in the backend database.</p></header>
    {notice && <p className="privacy-note configured" role="status">{notice}</p>}{error && <p className="privacy-note needs-key" role="alert">{error}</p>}
    <div className="provider-list">{providers.map((provider) => {
      const linked = accounts.filter((account) => account.provider === provider.id);
      return <article className="provider-card" key={provider.id}><div className="provider-mark">{provider.mark}</div><div className="provider-info"><h2>{provider.label}</h2><p>{provider.note}</p>{linked.map((account) => <div className="connected-account" key={account.id}><span><i />{account.name}</span><button type="button" className="text-button" onClick={() => void disconnect(account)}>Disconnect</button></div>)}</div><a className={`download-button ${!ready[provider.id] ? "button-disabled" : ""}`} href={ready[provider.id] ? `/api/social/${provider.id}/connect` : undefined} aria-disabled={!ready[provider.id]} onClick={(event) => { if (!ready[provider.id]) { event.preventDefault(); setError(`Add ${provider.id === "instagram" || provider.id === "facebook" ? "META" : provider.id.toUpperCase()} OAuth credentials and the HTTPS callback URL in backend/.env first.`); } }}>{linked.length ? "Add account" : ready[provider.id] ? "Connect" : "Setup needed"}</a></article>;
    })}</div>
    <section className="project-section queue-section"><h2>Publishing queue</h2>{posts.length === 0 ? <p className="section-help">No scheduled posts yet.</p> : <div className="queue-list">{posts.map((post) => <article className="queue-row" key={post.id}><div><strong>Clip {post.clip_number} · {providers.find((provider) => provider.id === post.provider)?.label || post.provider}</strong><span>{new Date(post.scheduled_at).toLocaleString()} · {post.status}</span>{post.error && <small>{post.error}</small>}{post.remote_url && <a href={post.remote_url} target="_blank" rel="noreferrer">View published post</a>}</div>{post.status === "queued" && <button className="text-button" type="button" onClick={() => void cancelPost(post)}>Cancel</button>}</article>)}</div>}</section>
    <section className="project-section"><h2>Deployment checklist</h2><p className="section-help">Register the HTTPS callback URL shown in the deployment guide with each provider. Provider review, app permissions, and account eligibility are controlled by the social platforms. Keep each API secret in the hosting provider’s secret manager.</p><p className="section-help">The schedule worker must run continuously with persistent storage and a single worker instance. Instagram uses a short-lived signed media URL; the other providers receive direct uploads from the worker.</p></section>
  </div></main>;
}

export default Settings;
