import { useProjects } from "../hooks/useCatalog";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { RANGE_OPTIONS, useFilters } from "../lib/filters";

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8420";

// Settings is deliberately small and honest: this deployment has no
// accounts, no tenancy, and no server-side preferences to store
// (ADR-009), so what's here is what actually exists — the client's own
// view filters, where it points, and what the live connection is doing.
export default function SettingsPage() {
  const { project, setProject, range, setRange } = useFilters();
  const { data: projectsPage } = useProjects();
  const { connected, streaming } = useLiveRefresh(project);

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Settings</h1>
        <span className="page__sub">client-side preferences and connection status</span>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card__head">
            <h2 className="card__title">View filters</h2>
          </div>
          <div className="stack" style={{ gap: 14 }}>
            <label className="field">
              <span className="field__label">Project</span>
              <select
                className="select"
                value={project ?? ""}
                onChange={(event) => setProject(event.target.value || undefined)}
              >
                <option value="">All projects</option>
                {(projectsPage?.projects ?? []).map((entry) => (
                  <option key={entry.project_id} value={entry.project_id}>
                    {entry.project_id} ({entry.runs} runs)
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="field__label">Default time range</span>
              <select
                className="select"
                value={range.label}
                onChange={(event) =>
                  setRange(RANGE_OPTIONS.find((r) => r.label === event.target.value) ?? range)
                }
              >
                {RANGE_OPTIONS.map((option) => (
                  <option key={option.label} value={option.label}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="card">
          <div className="card__head">
            <h2 className="card__title">Connection</h2>
          </div>
          <div className="kv">
            <span className="kv__k">Control plane</span>
            <span className="kv__v mono" style={{ fontSize: 12 }}>
              {API_BASE}
            </span>
            <span className="kv__k">Live stream</span>
            <span
              className="kv__v"
              style={{ color: connected ? "var(--status-good)" : "var(--status-critical)" }}
            >
              {connected ? (streaming ? "receiving events" : "connected") : "disconnected"}
            </span>
            <span className="kv__k">Refresh model</span>
            <span className="kv__v">SSE-driven</span>
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
            Views re-read when the server streams a new event, not on a timer. If the stream drops,
            data stays as-of the last event received until you navigate.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <h2 className="card__title">Not in this deployment</h2>
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          There are no user accounts, teams, or workspaces to configure: the MVP authenticates
          ingest with a single static API key and is explicitly not multi-tenant (ADR-009). Theme is
          remembered in this browser only.
        </p>
      </div>
    </div>
  );
}
