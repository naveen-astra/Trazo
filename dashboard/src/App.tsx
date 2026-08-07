import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import {
  IconAlert,
  IconBell,
  IconBrain,
  IconChevronDown,
  IconGraph,
  IconGrid,
  IconList,
  IconMoon,
  IconPlay,
  IconSearch,
  IconShield,
  IconSliders,
  IconSun,
  IconUsers,
  IconWrench,
} from "./components/Icons";
import { useProjects } from "./hooks/useCatalog";
import { useLiveRefresh } from "./hooks/useLiveRefresh";
import { useStats } from "./hooks/useStats";
import { useFilters } from "./lib/filters";

// Nav lists only surfaces this control plane actually serves. Sections a
// product like this often has but Trazo records no data for (datasets,
// evaluations, prompt diffs, alert rules, approvals, integrations) are
// deliberately absent rather than rendered as dead links.
const NAV = [
  {
    group: "Observe",
    items: [
      { to: "/", label: "Overview", icon: <IconGrid />, end: true },
      { to: "/runs", label: "Runs", icon: <IconList />, end: false },
      { to: "/traces", label: "Traces", icon: <IconGraph />, end: false },
      { to: "/agents", label: "Agents", icon: <IconUsers />, end: false },
      { to: "/tools", label: "Tools", icon: <IconWrench />, end: false },
    ],
  },
  {
    group: "Debug",
    items: [
      { to: "/replay", label: "Replay Studio", icon: <IconPlay />, end: false },
      { to: "/logs", label: "Logs", icon: <IconBrain />, end: false },
    ],
  },
  {
    group: "Govern",
    items: [
      { to: "/incidents", label: "Incidents", icon: <IconAlert />, end: false },
      { to: "/policy", label: "Policy", icon: <IconShield />, end: false },
    ],
  },
  {
    group: "Config",
    items: [{ to: "/settings", label: "Settings", icon: <IconSliders />, end: false }],
  },
];

type Theme = "dark" | "light";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("trazo-theme") as Theme | null) ?? "dark",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("trazo-theme", theme);
  }, [theme]);

  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const { project, setProject } = useFilters();
  const { data: stats } = useStats({ project });
  const { data: projectsPage } = useProjects();
  // One SSE subscription for the whole app: every list/aggregate view
  // re-reads the moment events land (see useLiveRefresh).
  const { connected, streaming } = useLiveRefresh(project);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const openIncidents = stats?.recent_detections.length ?? 0;
  const projects = projectsPage?.projects ?? [];

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="sidebar__brand">
          <div className="sidebar__mark" />
          <span className="sidebar__name">Trazo</span>
        </div>

        {NAV.map((section) => (
          <div key={section.group}>
            <div className="sidebar__group">{section.group}</div>
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? "nav-item nav-item--active" : "nav-item")}
              >
                <span className="nav-item__icon">{item.icon}</span>
                {item.label}
                {item.to === "/incidents" && openIncidents > 0 && (
                  <span className="nav-item__count">{openIncidents}</span>
                )}
              </NavLink>
            ))}
          </div>
        ))}

        <div className="sidebar__footer">
          <span
            className="chip"
            title={
              connected
                ? "Subscribed to the live event stream"
                : "Live stream disconnected — views refresh on navigation"
            }
          >
            <span
              className="chip__dot"
              style={{
                borderRadius: "50%",
                background: connected ? "var(--status-good)" : "var(--text-muted)",
                animation: streaming ? "live-pulse 1s ease-in-out infinite" : "none",
              }}
            />
            {connected ? (streaming ? "receiving" : "live") : "offline"}
          </span>
        </div>
      </nav>

      <div className="main">
        <header className="topbar">
          <form
            className="topbar__search"
            onSubmit={(event) => {
              event.preventDefault();
              const trimmed = query.trim();
              if (trimmed) navigate(`/runs/${encodeURIComponent(trimmed)}`);
            }}
          >
            <IconSearch />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Go to run by id…"
              aria-label="Go to run by id"
            />
          </form>

          {/* A real project filter, not a workspace switcher: Trazo has no
              tenancy (ADR-009), but project_id is on every row, so this
              scopes the API calls for real. */}
          <label className="select-wrap" title="Filter every view by project">
            <select
              className="select"
              value={project ?? ""}
              onChange={(event) => setProject(event.target.value || undefined)}
            >
              <option value="">All projects</option>
              {projects.map((entry) => (
                <option key={entry.project_id} value={entry.project_id}>
                  {/* The name the SDK was configured with, not the hash of
                      it — "research-assistant", not proj_85c0c89d12f6… */}
                  {entry.name} ({entry.runs})
                </option>
              ))}
            </select>
            <IconChevronDown />
          </label>

          <NavLink
            to="/incidents"
            className="icon-button"
            style={{ position: "relative" }}
            aria-label={`${openIncidents} open incidents`}
            title={`${openIncidents} recent detections`}
          >
            <IconBell />
            {openIncidents > 0 && <span className="icon-button__badge">{openIncidents}</span>}
          </NavLink>

          <button
            type="button"
            className="icon-button"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>
        </header>
        <Outlet />
      </div>
    </div>
  );
}
