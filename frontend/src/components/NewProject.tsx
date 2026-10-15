import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

type ClipMode = "best-parts" | "sequence";
type ClipDuration = 30 | 60 | 90;
type Clip = { number: number; duration_seconds: number; start_seconds?: number; reason?: string; url: string; captions_url?: string | null; aspect_ratio?: string; captions_burned?: boolean };
type ProjectResult = { id: string; status: string; progress?: string | null; clips?: Clip[]; clip_url?: string | null; error?: string | null };
type PublishAccount = { provider: "youtube" | "instagram" | "tiktok" | "facebook" | "x" | "linkedin"; id: string; name: string };
const clipDurations: ClipDuration[] = [30, 60, 90];

async function readResponse(response: Response) {
  return response.json().catch(() => ({})) as Promise<Record<string, unknown>>;
}

function NewProject() {
  const [inputType, setInputType] = useState<"upload" | "url">("upload");
  const [clipMode, setClipMode] = useState<ClipMode>("sequence");
  const [clipDuration, setClipDuration] = useState<ClipDuration>(30);
  const [generateSubtitles, setGenerateSubtitles] = useState(false);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [clips, setClips] = useState<Clip[]>([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [openAiConfigured, setOpenAiConfigured] = useState(false);
  const [apiReachable, setApiReachable] = useState(true);
  const [editValues, setEditValues] = useState<Record<number, { trimStart: string; trimEnd: string; aspectRatio: string }>>({});
  const [editingClip, setEditingClip] = useState<number | null>(null);
  const [publishAccounts, setPublishAccounts] = useState<PublishAccount[]>([]);
  const [selectedTargets, setSelectedTargets] = useState<string[]>([]);
  const [privacyOptions, setPrivacyOptions] = useState<Record<string, string[]>>({});
  const [privacyByAccount, setPrivacyByAccount] = useState<Record<string, string>>({});
  const [privacyLoaded, setPrivacyLoaded] = useState<Record<string, boolean>>({});
  const [publishCadence, setPublishCadence] = useState<"6-hours" | "daily">("6-hours");
  const [publishAt, setPublishAt] = useState(() => { const at = new Date(Date.now() + 10 * 60 * 1000); at.setMinutes(Math.ceil(at.getMinutes() / 5) * 5, 0, 0); return new Date(at.getTime() - at.getTimezoneOffset() * 60000).toISOString().slice(0, 16); });
  const [publishCaption, setPublishCaption] = useState("");

  useEffect(() => {
    let active = true;
    fetch("/api/capabilities")
      .then(async (response) => {
        const data = await readResponse(response);
        if (!response.ok) throw new Error("API unavailable");
        if (active) {
          setOpenAiConfigured(Boolean(data.openai_configured));
          setApiReachable(true);
        }
      })
      .catch(() => { if (active) setApiReachable(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!clips.length) return;
    const loadAccounts = async () => {
      try {
        const response = await fetch("/api/social/accounts");
        if (!response.ok) return;
        const accounts = await response.json() as PublishAccount[];
        setPublishAccounts(accounts);
        const tiktok = accounts.filter((account) => account.provider === "tiktok");
        const results = await Promise.all(tiktok.map(async (account) => {
          const result = await fetch(`/api/social/tiktok/accounts/${encodeURIComponent(account.id)}/privacy-options`);
          if (!result.ok) return [account.id, []] as const;
          const data = await result.json() as { options: string[] };
          return [account.id, data.options] as const;
        }));
        setPrivacyOptions(Object.fromEntries(results));
        setPrivacyLoaded(Object.fromEntries(tiktok.map((account) => [account.id, true])));
      } catch { setPublishAccounts([]); }
    };
    void loadAccounts();
  }, [clips.length]);

  const waitForProject = async (projectId: string): Promise<ProjectResult> => {
    for (let attempt = 0; attempt < 1800; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const response = await fetch(`/api/projects/${projectId}`);
      const project = await readResponse(response) as unknown as ProjectResult;
      if (!response.ok) throw new Error("Could not read the project's processing status.");
      if (project.status === "processing" || project.status === "queued") {
        setMessage(project.progress || "Processing your video…");
      }
      if (project.status === "completed" || project.status === "failed") return project;
    }
    throw new Error("Processing is still running. Your project will remain on the dashboard.");
  };

  const handleGenerate = async () => {
    setMessage("");
    setIsError(false);
    setClips([]);
    if (!apiReachable) {
      setMessage("The API is unavailable. Start the backend server and refresh this page.");
      setIsError(true);
      return;
    }
    if (clipMode === "best-parts" && !openAiConfigured) {
      setMessage("Best Parts requires an OpenAI API key. Add it to backend/.env and restart the backend, or choose Sequence Wise.");
      setIsError(true);
      return;
    }
    if (generateSubtitles && !openAiConfigured) {
      setMessage("AI subtitles require an OpenAI API key. Add it to backend/.env and restart the backend.");
      setIsError(true);
      return;
    }
    if (inputType === "upload" && !videoFile) {
      setMessage("Choose a video file first.");
      setIsError(true);
      return;
    }
    if (inputType === "url" && !videoUrl.trim()) {
      setMessage("Paste a YouTube or Vimeo video link first.");
      setIsError(true);
      return;
    }
    if (videoFile && videoFile.size > 2 * 1024 * 1024 * 1024) {
      setMessage("The maximum video size is 2 GB.");
      setIsError(true);
      return;
    }

    const formData = new FormData();
    formData.append("source_type", inputType);
    formData.append("clip_mode", clipMode);
    formData.append("clip_duration", String(clipDuration));
    formData.append("generate_subtitles", String(generateSubtitles));
    if (inputType === "upload" && videoFile) formData.append("video_file", videoFile);
    if (inputType === "url") formData.append("video_url", videoUrl.trim());

    setIsSubmitting(true);
    setMessage("Starting your project…");
    try {
      const response = await fetch("/api/projects", { method: "POST", body: formData });
      const data = await readResponse(response) as unknown as ProjectResult & { detail?: string };
      if (!response.ok) throw new Error(data.detail || "Unable to create the project.");
      setActiveProjectId(data.id);
      const status = await waitForProject(data.id);
      if (status.status === "completed") {
        const readyClips = status.clips?.length ? status.clips : status.clip_url ? [{ number: 1, duration_seconds: clipDuration, url: status.clip_url }] : [];
        setClips(readyClips);
        setMessage(`${readyClips.length} clip${readyClips.length === 1 ? " is" : "s are"} ready. Your project is also saved on the dashboard.`);
      } else {
        setMessage(status.error || "Clip processing could not be completed.");
        setIsError(true);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to reach the API.");
      setIsError(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const saveClipEdit = async (clip: Clip) => {
    const values = editValues[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: "9:16" };
    setEditingClip(clip.number);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${activeProjectId}/clips/${clip.number}/edit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trim_start: Number(values.trimStart), trim_end: Number(values.trimEnd), aspect_ratio: values.aspectRatio }),
      });
      const data = await readResponse(response) as unknown as Clip & { detail?: string };
      if (!response.ok) throw new Error(data.detail || "Could not edit this clip.");
      setClips((current) => current.map((item) => item.number === clip.number ? data : item));
      setEditValues((current) => ({ ...current, [clip.number]: { trimStart: "0", trimEnd: String(data.duration_seconds), aspectRatio: data.aspect_ratio || "9:16" } }));
      setMessage(`Clip ${clip.number} updated.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not edit this clip.");
      setIsError(true);
    } finally {
      setEditingClip(null);
    }
  };

  const scheduleClips = async () => {
    const targets = publishAccounts.filter((account) => selectedTargets.includes(`${account.provider}|${account.id}`)).map(({ provider, id }) => ({ provider, account_id: id, ...(provider === "tiktok" ? { privacy_level: privacyByAccount[id] } : {}) }));
    if (!activeProjectId || !targets.length) { setMessage("Connect an account and choose at least one publishing destination."); setIsError(true); return; }
    try {
      const response = await fetch(`/api/projects/${activeProjectId}/schedule`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ targets, cadence: publishCadence, first_at: new Date(publishAt).toISOString(), caption: publishCaption }) });
      const data = await readResponse(response) as { scheduled?: number; detail?: string };
      if (!response.ok) throw new Error(data.detail || "Could not schedule clips.");
      setIsError(false); setMessage(`${data.scheduled} post${data.scheduled === 1 ? "" : "s"} added to your publishing queue.`);
    } catch (error) { setIsError(true); setMessage(error instanceof Error ? error.message : "Could not schedule clips."); }
  };

  return <main className="new-project-page">
    <div className="new-project">
      <header className="new-project-header">
        <Link className="back-link" to="/">← Back to dashboard</Link>
        <h1>New project</h1>
        <p>Turn a long video into short clips ready to preview and download.</p>
      </header>

      <section className="project-section">
        <h2>1. Choose your video</h2>
        <div className="option-grid">
          <button type="button" className={`option-card ${inputType === "upload" ? "active" : ""}`} aria-pressed={inputType === "upload"} disabled={isSubmitting} onClick={() => setInputType("upload")}>
            <span className="option-icon">📁</span><strong>Upload video</strong><span>Select an MP4, MOV, MKV, WEBM, AVI, M4V, MPEG, or MPG file.</span>
          </button>
          <button type="button" className={`option-card ${inputType === "url" ? "active" : ""}`} aria-pressed={inputType === "url"} disabled={isSubmitting} onClick={() => setInputType("url")}>
            <span className="option-icon">🔗</span><strong>Import a link</strong><span>Import a public YouTube, Vimeo, Twitch, Google Drive, or Dropbox video.</span>
          </button>
        </div>
        {inputType === "upload" ? <div className="upload-box">
          <label htmlFor="video-file">Choose a video file <span>(max 2 GB)</span></label>
          <input id="video-file" type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo,.m4v,.mpeg,.mpg" disabled={isSubmitting} onChange={(event) => setVideoFile(event.target.files?.[0] ?? null)} />
          {videoFile && <p className="file-selection">Selected: <strong>{videoFile.name}</strong> · {(videoFile.size / (1024 * 1024)).toFixed(1)} MB</p>}
        </div> : <div className="url-box">
          <label htmlFor="video-url">Public video link</label>
          <input id="video-url" type="url" placeholder="https://www.youtube.com/watch?v=…" value={videoUrl} disabled={isSubmitting} onChange={(event) => setVideoUrl(event.target.value)} />
          <p>Public links only. You must have permission to download and use the video.</p>
        </div>}
      </section>

      <section className="project-section">
        <h2>2. Choose clipping mode</h2>
        <div className="option-grid">
          <button type="button" className={`option-card ${clipMode === "best-parts" ? "active" : ""}`} aria-pressed={clipMode === "best-parts"} disabled={isSubmitting} onClick={() => setClipMode("best-parts")}>
            <span className="option-icon">⭐</span><strong>Best Parts</strong><span>OpenAI transcribes the audio and chooses engaging moments.</span>
          </button>
          <button type="button" className={`option-card ${clipMode === "sequence" ? "active" : ""}`} aria-pressed={clipMode === "sequence"} disabled={isSubmitting} onClick={() => setClipMode("sequence")}>
            <span className="option-icon">📑</span><strong>Sequence Wise</strong><span>Split the full video into consecutive clips at the selected interval. Runs locally.</span>
          </button>
        </div>
        {clipMode === "best-parts" && <div className={`privacy-note ${openAiConfigured ? "configured" : "needs-key"}`} role="note">
          {openAiConfigured ? "Best Parts sends extracted audio for transcription and the resulting transcript to OpenAI. Your video file itself is not sent to OpenAI. API charges may apply." : <>Best Parts needs an OpenAI API key. Copy <code>backend/.env.example</code> to <code>backend/.env</code>, add your key, then restart the backend. <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">Create an API key</a>. Sequence Wise works without a key.</>}
        </div>}
      </section>

      <section className="project-section">
        <h2>3. Choose clip length</h2>
        <div className="duration-options" role="group" aria-label="Clip length">
          {clipDurations.map((duration) => <button type="button" className={`duration-option ${clipDuration === duration ? "active" : ""}`} aria-pressed={clipDuration === duration} disabled={isSubmitting} onClick={() => setClipDuration(duration)} key={duration}>{duration}s</button>)}
        </div>
        <p className="section-help">Sequence Wise starts a new clip every {clipDuration} seconds. The final clip may be shorter.</p>
      </section>

      <section className="project-section subtitle-section">
        <h2>4. AI subtitles <span className="optional-label">Optional</span></h2>
        <label className="subtitle-toggle"><input type="checkbox" checked={generateSubtitles} disabled={isSubmitting} onChange={(event) => setGenerateSubtitles(event.target.checked)} /><span>Create timed captions for each clip</span></label>
        <p className="section-help">Uses OpenAI speech transcription, makes a downloadable WebVTT file, and burns readable captions into clips when the video encoder supports it. Extracted audio is sent to OpenAI; charges may apply.</p>
        {generateSubtitles && !openAiConfigured && <p className="key-warning">Add an OpenAI API key in <code>backend/.env</code> and restart the backend. <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">Create an API key</a>.</p>}
      </section>

      <button className="generate-button" type="button" onClick={handleGenerate} disabled={isSubmitting || !apiReachable}>
        {isSubmitting ? "Processing video…" : "✨ Generate clips"}
      </button>
      {!apiReachable && <p className="project-message error-message" role="alert">The backend API is not reachable. Start the backend server and reload.</p>}
      {message && <p className={`project-message ${isError ? "error-message" : ""}`} role={isError ? "alert" : "status"}>{message}</p>}

      {clips.length > 0 && <section className="result-section" aria-label="Generated clips">
        <h2>Your clips</h2>
        <div className="result-grid">{clips.map((clip) => <article className="result-card" key={clip.url}>
          <video controls preload="metadata" style={{ aspectRatio: clip.aspect_ratio?.replace(":", " / ") || "16 / 9" }} src={clip.url}>{clip.captions_url && <track kind="captions" srcLang="und" label="AI captions" src={clip.captions_url} />}Your browser does not support video playback.</video>
          <div className="result-card-details"><div><strong>Clip {clip.number}</strong><span>{Math.ceil(clip.duration_seconds)} seconds{clip.start_seconds !== undefined ? ` · starts at ${Math.floor(clip.start_seconds)}s` : ""}</span></div><a className="download-button" href={clip.url} download>Download</a></div>
          {clip.reason && <p className="clip-reason">{clip.reason}</p>}
          {clip.captions_url && <p className="clip-actions">{clip.captions_burned && <span>On-screen captions included · </span>}<a href={clip.captions_url} download>Download captions (.vtt)</a></p>}
          <details className="clip-editor"><summary>Edit clip</summary>
            <div className="clip-edit-fields">
              <label>Trim start (sec)<input type="number" min="0" step="0.1" value={(editValues[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: clip.aspect_ratio || "9:16" }).trimStart} onChange={(event) => setEditValues((current) => ({ ...current, [clip.number]: { ...(current[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: "9:16" }), trimStart: event.target.value } }))} /></label>
              <label>Trim end (sec)<input type="number" min="0.1" step="0.1" value={(editValues[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: clip.aspect_ratio || "9:16" }).trimEnd} onChange={(event) => setEditValues((current) => ({ ...current, [clip.number]: { ...(current[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: "9:16" }), trimEnd: event.target.value } }))} /></label>
              <label>Aspect ratio<select value={(editValues[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: clip.aspect_ratio || "9:16" }).aspectRatio} onChange={(event) => setEditValues((current) => ({ ...current, [clip.number]: { ...(current[clip.number] ?? { trimStart: "0", trimEnd: String(clip.duration_seconds), aspectRatio: "9:16" }), aspectRatio: event.target.value } }))}><option>9:16</option><option>1:1</option><option>16:9</option></select></label>
            </div>
            <button type="button" className="download-button" disabled={editingClip === clip.number} onClick={() => void saveClipEdit(clip)}>{editingClip === clip.number ? "Rendering…" : "Save edit"}</button>
            <p className="section-help">Editing renders a new file and may take a moment. Burned captions remain in the video; the separate VTT captions file is cleared because its timing changes.</p>
          </details>
        </article>)}</div>
      </section>}
      {clips.length > 0 && <section className="project-section schedule-section"><h2>5. Schedule cross-posts</h2>
        {publishAccounts.length === 0 ? <p className="section-help">No social accounts connected yet. Set up provider credentials and connect an account in <Link to="/settings">Publishing settings</Link>.</p> : <>
          <p className="section-help">Each generated clip is queued for every selected destination, spaced by the cadence you choose. The worker publishes from your hosted HTTPS server.</p>
          <div className="schedule-targets">{publishAccounts.map((account) => { const key = `${account.provider}|${account.id}`; const isSelected = selectedTargets.includes(key); return <div className="schedule-target" key={key}><label><input type="checkbox" checked={isSelected} onChange={(event) => setSelectedTargets((current) => event.target.checked ? [...current, key] : current.filter((target) => target !== key))} /><span>{account.name} · {account.provider}</span></label>{account.provider === "tiktok" && isSelected && <>{(privacyOptions[account.id] || []).length ? <label className="privacy-choice">TikTok audience<select required value={privacyByAccount[account.id] || ""} onChange={(event) => setPrivacyByAccount((current) => ({ ...current, [account.id]: event.target.value }))}><option value="">Choose audience…</option>{(privacyOptions[account.id] || []).map((option) => <option key={option} value={option}>{({ PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers", SELF_ONLY: "Only me" } as Record<string, string>)[option] || option}</option>)}</select></label> : <p className="privacy-load-note">{privacyLoaded[account.id] ? "No TikTok posting audiences returned. Reconnect the account and check video.publish access." : "Loading TikTok audience options…"}</p>}</>}</div>; })}</div>
          <div className="schedule-fields"><label>Post spacing<select value={publishCadence} onChange={(event) => setPublishCadence(event.target.value as "6-hours" | "daily")}><option value="6-hours">Every 6 hours</option><option value="daily">Every day</option></select></label><label>First post time<input type="datetime-local" value={publishAt} onChange={(event) => setPublishAt(event.target.value)} /></label></div>
          <label className="caption-field">Caption for each destination<textarea maxLength={2200} rows={3} value={publishCaption} onChange={(event) => setPublishCaption(event.target.value)} placeholder="Add a caption (optional)" /></label>
          <button className="primary-button" type="button" onClick={() => void scheduleClips()}>Add clips to schedule</button>
        </>}
      </section>}
    </div>
  </main>;
}

export default NewProject;
