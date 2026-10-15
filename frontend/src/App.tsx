// import { useState } from "react";

// type IconName =
//   | "home"
//   | "library"
//   | "analytics"
//   | "settings"
//   | "bell"
//   | "plus"
//   | "arrow"
//   | "more";

// function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
//   const paths: Record<IconName, React.ReactNode> = {
//     home: <><path d="m3 9 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9Z" /><path d="M9 21v-6h6v6" /></>,
//     library: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m10 9 5 3-5 3V9Z" /></>,
//     analytics: <><path d="M4 20V10" /><path d="M10 20V4" /><path d="M16 20v-7" /><path d="M22 20H2" /></>,
//     settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 2.12-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V20.3h-3v-.08A1.7 1.7 0 0 0 10.68 18.66a1.7 1.7 0 0 0-1.88.34l-.06.06-2.12-2.12.06-.06A1.7 1.7 0 0 0 7.02 15a1.7 1.7 0 0 0-1.56-1.03H5.4v-3h.08A1.7 1.7 0 0 0 7.02 9.94a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.12-2.12.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.7h3v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06L19.8 8l-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.08v3h-.08A1.7 1.7 0 0 0 19.4 15Z" /></>,
//     bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
//     plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
//     arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
//     more: <><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></>,
//   };

//   return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
// }

// const projects = [
//   { title: "Marketing Masterclass", source: "YouTube import", date: "Today, 10:42 AM", clips: 8, color: "purple" },
//   { title: "Product Launch Webinar", source: "Uploaded video", date: "Yesterday", clips: 12, color: "orange" },
//   { title: "Founder Interview", source: "YouTube import", date: "Aug 10, 2026", clips: 6, color: "blue" },
// ];

// function App() {
//   const [notice, setNotice] = useState("");

//   const createProject = () => {
//     setNotice("New project creation will be connected in the next milestone.");
//   };

//   return (
//     <div className="app-shell">
//       <aside className="sidebar">
//         <a className="brand" href="#dashboard" aria-label="ClipForgeAI dashboard"><span className="brand-mark">C</span><span>ClipForge<span className="brand-ai">AI</span></span></a>
//         <nav className="side-nav" aria-label="Main navigation">
//           <a className="nav-link active" href="#dashboard"><Icon name="home" />Dashboard</a>
//           <a className="nav-link" href="#projects"><Icon name="library" />Projects</a>
//           <a className="nav-link" href="#analytics"><Icon name="analytics" />Analytics</a>
//         </nav>
//         <div className="sidebar-bottom">
//           <a className="nav-link" href="#settings"><Icon name="settings" />Settings</a>
//           <div className="plan-card"><span className="plan-icon">✦</span><div><strong>Free plan</strong><span>3 of 5 videos used</span></div><div className="usage"><i /></div><a href="#upgrade">Upgrade</a></div>
//           <div className="profile"><div className="avatar">AK</div><div><strong>Alex Kumar</strong><span>Free workspace</span></div><button type="button" aria-label="Open account menu">⌄</button></div>
//         </div>
//       </aside>

//       <main className="main-content" id="dashboard">
//         <header className="topbar"><div className="mobile-brand">ClipForge<span>AI</span></div><div className="topbar-actions"><button className="icon-button" type="button" aria-label="Notifications"><Icon name="bell" size={19} /><span className="notification-dot" /></button><button className="help-button" type="button">?</button></div></header>
//         <div className="dashboard-content">
//           <section className="hero"><div><p className="eyebrow">YOUR WORKSPACE</p><h1>Welcome back, Alex <span>👋</span></h1><p className="subtitle">Turn your long-form videos into standout short clips.</p></div><button className="primary-button" type="button" onClick={createProject}><Icon name="plus" size={18} />New project</button></section>
//           {notice && <p className="notice" role="status">{notice}</p>}

//           <section className="stats-grid" aria-label="Workspace statistics">
//             <article className="stat-card"><div className="stat-icon purple"><Icon name="library" size={21} /></div><div><span>Total projects</span><strong>12</strong><small><b>+2</b> this month</small></div></article>
//             <article className="stat-card"><div className="stat-icon orange"><Icon name="analytics" size={21} /></div><div><span>Clips generated</span><strong>87</strong><small><b>+18</b> this month</small></div></article>
//             <article className="stat-card"><div className="stat-icon blue"><span className="play-symbol">▶</span></div><div><span>Total views</span><strong>24.8K</strong><small><b>+12.5%</b> vs. last month</small></div></article>
//           </section>

//           <section className="projects-section" id="projects"><div className="section-heading"><div><h2>Recent projects</h2><p>Pick up where you left off.</p></div><a href="#all-projects">View all <Icon name="arrow" size={16} /></a></div><div className="project-list">
//             {projects.map((project) => <article className="project-row" key={project.title}><div className={`project-thumb ${project.color}`}><span>▶</span></div><div className="project-details"><h3>{project.title}</h3><p>{project.source}<i />{project.date}</p></div><div className="clip-count"><strong>{project.clips}</strong><span>clips</span></div><button className="more-button" type="button" aria-label={`More actions for ${project.title}`}><Icon name="more" size={21} /></button></article>)}
//           </div></section>

//           <section className="empty-card"><div className="empty-icon"><Icon name="plus" size={21} /></div><div><h2>Ready to create your next viral clip?</h2><p>Upload a video or paste a YouTube link to get started.</p></div><button className="text-button" type="button" onClick={createProject}>Create project <Icon name="arrow" size={16} /></button></section>
//         </div>
//       </main>
//     </div>
//   );
// }

// export default App;

import { Navigate, Route, Routes } from "react-router-dom";
import Dashboard from "./components/Dashboard";
import NewProject from "./components/NewProject";
import Settings from "./components/Settings";
import AuthGate from "./components/AuthGate";

function App() {
  return (
    <AuthGate><Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/new-project" element={<NewProject />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes></AuthGate>
  );
}

export default App;
