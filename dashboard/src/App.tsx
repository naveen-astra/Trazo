import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import {
  IconAlert,
  IconGrid,
  IconList,
  IconMoon,
  IconSearch,
  IconShield,
  IconSun,
} from "./components/Icons";
import { useStats } from "./hooks/useStats";

// Nav lists only surfaces this control plane actually serves. Sections
// the API has no data for (agent registries, datasets, evaluations,
// approvals, integrations) are deliberately absent rather than rendered
// as dead links — a nav item that goes nowhere is worse than a shorter
// nav (the README's "Project status" table makes the same promise).
const NAV = [
  {
    group: "Observe",
    items: [
      { to: "/", label: "Overview", icon: <IconGrid />, end: true },
      { to: "/runs", label: "Runs", icon: <IconList />, end: false },
    ],
  },
  {
    group: "Govern",
    items: [
      { to: "/incidents", label: "Incidents", icon: <IconAlert />, end: false },
      { to: "/policy", label: "Policy", icon: <IconShield />, end: false },
    ],
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
  // Only feeds the Incidents badge; a failed/pending stats call means no
  // badge, never a broken nav.
  const { data: stats } = useStats();
  const openIncidents = stats?.recent_detections.length ?? 0;

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

        <div className="sidebar__footer">observability · replay · governance</div>
      </nav>

      <div className="main">
        <header className="topbar">
          <label className="topbar__search">
            <IconSearch />
            <input placeholder="Search runs by id…" disabled />
          </label>
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
