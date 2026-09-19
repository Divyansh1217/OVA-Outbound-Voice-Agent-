import { NavLink, Outlet } from "react-router-dom";

export default function Layout() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo">+</div>
          <div>
            <div className="brand-name">HealthLine Voice</div>
            <div className="brand-sub">Doctor Dashboard</div>
          </div>
        </div>

        <nav className="nav-list">
          <NavLink to="/" end className="nav-link">
            <span className="nav-emoji">▦</span> Dashboard
          </NavLink>
          <NavLink to="/patients" className="nav-link">
            <span className="nav-emoji">👤</span> Patients
          </NavLink>
          <NavLink to="/calls" className="nav-link">
            <span className="nav-emoji">📞</span> Calls
          </NavLink>
        </nav>

        <div className="sidebar-foot">
          AI outbound calls · LiveKit + Groq
        </div>
      </aside>

      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}