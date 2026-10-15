import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

type Clip = { number: number; duration_seconds: number; url: string };
type Project = {
  id: string;
  source_type: "upload" | "url";
  source_name: string;
  clip_mode: "best-parts" | "sequence";
  clip_duration: number;
  status: "queued" | "processing" | "completed" | "failed" | "awaiting-source";
  progress?: string | null;
  created_at: string;
  clips: Clip[];
  error?: string | null;
};

function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const loadProjects = async () => {
      try {
        const response = await fetch("/api/projects");
        if (!response.ok) throw new Error("Could not load your projects.");
        const data = await response.json() as Project[];
        if (active) {
          setProjects(data);
          setError("");
        }
      } catch (loadError) {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not connect to the Clipforge API.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void loadProjects();
    const timer = window.setInterval(loadProjects, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const clipCount = projects.reduce((total, project) => total + project.clips.length, 0);
  const activeCount = projects.filter((project) => project.status === "queued" || project.status === "processing").length;

  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="brand" to="/" aria-label="ClipForgeAI dashboard"><span className="brand-mark">C</span><span>ClipForge<span className="brand-ai">AI</span></span></Link>
      <nav className="side-nav" aria-label="Main navigation">
        <Link className="nav-link active" to="/"><span aria-hidden="true">⌂</span>Dashboard</Link>
        <a className="nav-link" href="#projects"><span aria-hidden="true">▤</span>Projects</a>
        <Link className="nav-link" to="/settings"><span aria-hidden="true">⚙</span>Publishing</Link>
      </nav>
      <div className="sidebar-bottom">
        <div className="plan-card"><span className="plan-icon">✦</span><div><strong>Local workspace</strong><span>Videos stay on this device unless you choose Best Parts.</span></div></div>
        <div className="profile"><div className="avatar">CF</div><div><strong>ClipForgeAI</strong><span>Private workspace</span></div><button type="button" aria-label="Sign out" onClick={() => { void fetch("/api/auth/logout", { method: "POST" }).then(() => window.location.reload()); }}>↪</button></div>
      </div>
    </aside>

    <main className="main-content" id="dashboard">
      <header className="topbar"><div className="mobile-brand">ClipForge<span>AI</span></div><div className="api-status"><i className={error ? "offline" : "online"} />{error ? "API disconnected" : "Workspace ready"}</div></header>
      <div className="dashboard-content">
        <section className="hero">
          <div><p className="eyebrow">YOUR WORKSPACE</p><h1>Your video workspace <span>✦</span></h1><p className="subtitle">Create, track, and download clips from your videos.</p></div>
          <button className="primary-button" type="button" onClick={() => navigate("/new-project")}>＋ New project</button>
        </section>
        {error && <p className="notice error-notice" role="alert">{error} Start the backend server, then refresh this page.</p>}

        <section className="stats-grid" aria-label="Workspace statistics">
          <article className="stat-card"><div className="stat-icon purple"><span>▤</span></div><div><span>Projects</span><strong>{projects.length}</strong><small>Saved on this device</small></div></article>
          <article className="stat-card"><div className="stat-icon orange"><span>▶</span></div><div><span>Clips ready</span><strong>{clipCount}</strong><small>Available to preview and download</small></div></article>
          <article className="stat-card"><div className="stat-icon blue"><span>◷</span></div><div><span>In progress</span><strong>{activeCount}</strong><small>Processing jobs</small></div></article>
        </section>

        <section className="projects-section" id="projects">
          <div className="section-heading"><div><h2>Projects</h2><p>Recent work saved by ClipforgeAI.</p></div><button className="text-button" type="button" onClick={() => navigate("/new-project")}>New project →</button></div>
          {loading ? <div className="project-list empty-projects">Loading projects…</div> : projects.length === 0 ? <div className="project-list empty-projects"><h3>No projects yet</h3><p>Upload a video or import a YouTube or Vimeo link to create your first clips.</p><button className="primary-button" type="button" onClick={() => navigate("/new-project")}>Create your first project</button></div> :
            <div className="project-list">
              {projects.map((project, index) => <article className="project-row" key={project.id}>
                <div className={`project-thumb ${["purple", "orange", "blue"][index % 3]}`}><span>▶</span></div>
                <div className="project-details"><h3 title={project.source_name}>{project.source_name || "Untitled video"}</h3><p>{project.source_type === "upload" ? "Uploaded video" : "Video link"}<i />{new Date(project.created_at).toLocaleString()}<i /><span className={`status-text ${project.status}`}>{project.status === "processing" || project.status === "queued" ? project.progress || project.status : project.status}</span></p>{project.error && <p className="project-error">{project.error}</p>}
                  {project.clips.length > 0 && <div className="dashboard-clips">{project.clips.map((clip) => <a href={clip.url} target="_blank" rel="noreferrer" key={clip.url}>Clip {clip.number} · {Math.ceil(clip.duration_seconds)}s</a>)}</div>}
                </div>
                <div className="clip-count"><strong>{project.clips.length}</strong><span>clips</span></div>
              </article>)}
            </div>}
        </section>
        <section className="empty-card"><div className="empty-icon">✦</div><div><h2>Ready for another video?</h2><p>Choose a clip length and create a chronological sequence or AI-selected highlights.</p></div><button className="text-button" type="button" onClick={() => navigate("/new-project")}>Create project →</button></section>
      </div>
    </main>
  </div>;
}

export default Dashboard;
