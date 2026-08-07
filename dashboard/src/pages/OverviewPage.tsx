import { Link } from "react-router-dom";

import type { DetectionOut } from "../api/runApi";
import CostDonut from "../components/charts/CostDonut";
import RunsOverTimeChart from "../components/charts/RunsOverTimeChart";
import { IconAlert, IconArrowRight, IconChevronDown } from "../components/Icons";
import LiveBadge from "../components/LiveBadge";
import StatTile from "../components/StatTile";
import StatusBadge from "../components/StatusBadge";
import { useProjectName } from "../hooks/useCatalog";
import { useRuns } from "../hooks/useRuns";
import { useStats } from "../hooks/useStats";
import { RANGE_OPTIONS, useFilters } from "../lib/filters";

const SEVERITY_COLOR: Record<string, string> = {
  info: "var(--text-muted)",
  warn: "var(--status-warning)",
  critical: "var(--status-critical)",
};

function relativeTime(iso: string): string {
  const deltaMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(deltaMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function detectionTitle(detection: DetectionOut): string {
  const named: Record<string, string> = {
    loop: "Agent loop detected",
    budget: "Budget limit exceeded",
    thrash: "Tool thrashing detected",
    drift: "Goal drift detected",
  };
  return named[detection.detector] ?? `${detection.detector} detected`;
}

function RangePicker() {
  const { range, setRange } = useFilters();
  return (
    <label className="select-wrap select-wrap--sm">
      <select
        className="select select--sm"
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
      <IconChevronDown size={12} />
    </label>
  );
}

export default function OverviewPage() {
  const { project, range } = useFilters();
  const { data: stats, isLoading, isError, error } = useStats({ days: range.days, project });
  const { data: runsPage } = useRuns(project ? { project } : {});
  const projectName = useProjectName();

  if (isLoading && !stats) {
    return (
      <div className="page">
        <p className="muted">Loading overview&hellip;</p>
      </div>
    );
  }

  if (isError || !stats) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load stats: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const runs = runsPage?.runs ?? [];
  const dailyRuns = stats.daily.map((d) => d.runs);
  const dailyFailed = stats.daily.map((d) => d.failed_runs);
  const dailyCost = stats.daily.map((d) => d.cost_usd);

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Overview</h1>
        <span className="page__sub">
          {stats.window_runs} run{stats.window_runs === 1 ? "" : "s"}
          {project ? ` in ${project}` : ""} · {range.label.toLowerCase()}
        </span>
        <span style={{ marginLeft: "auto" }} />
        <RangePicker />
      </div>

      <div className="stat-grid">
        <StatTile
          label="Total Runs"
          value={String(stats.total_runs)}
          trend={dailyRuns}
          trendColor="var(--series-1)"
          delta={stats.deltas.runs_pct}
          foot="no prior window"
        />
        <StatTile
          label="Failed Runs"
          value={String(stats.failed_runs)}
          trend={dailyFailed}
          trendColor="var(--status-critical)"
          delta={stats.deltas.failed_runs_pct}
          riseIsGood={false}
          foot="no prior window"
        />
        {/* No sparkline or delta: "active" is an instantaneous count with
            no per-day series behind it. */}
        <StatTile label="Active Runs" value={String(stats.active_runs)} foot="currently running" />
        <StatTile
          label="Total Cost"
          value={`$${stats.total_cost_usd.toFixed(2)}`}
          trend={dailyCost}
          trendColor="var(--series-3)"
          delta={stats.deltas.cost_pct}
          riseIsGood={false}
          foot="no prior window"
        />
        <StatTile
          label="Policy Denials"
          value={String(stats.policy_denials)}
          foot="deny + escalate"
        />
      </div>

      <div className="grid-2">
        <div className="card">
          {/* No range picker here: the one in the page head already drives
              this chart's window, and a second control bound to the same
              state reads as an independent filter that doesn't work. */}
          <div className="card__head">
            <h2 className="card__title">Runs over time</h2>
            <span className="muted" style={{ fontSize: 12 }}>
              {range.label.toLowerCase()}
            </span>
          </div>
          <RunsOverTimeChart daily={stats.daily} />
        </div>

        <div className="card">
          <div className="card__head">
            <h2 className="card__title">Cost by project</h2>
          </div>
          <CostDonut costs={stats.cost_by_project} total={stats.total_cost_usd} />
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card__head">
            <h2 className="card__title">Live runs</h2>
            <Link to="/runs" className="chip">
              View all <IconArrowRight />
            </Link>
          </div>
          {runs.length === 0 ? (
            <div className="empty-state">
              No runs yet — instrument an agent with the SDK to see it here.
            </div>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Project</th>
                    <th>Status</th>
                    <th className="table__num">Events</th>
                    <th className="table__num">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.slice(0, 7).map((run) => (
                    <tr key={run.run_id}>
                      <td>
                        <Link className="table__mono" to={`/runs/${run.run_id}`}>
                          {run.run_id.slice(0, 18)}…
                        </Link>
                      </td>
                      <td className="muted">{projectName(run.project_id)}</td>
                      <td>
                        <span className="row" style={{ gap: 6 }}>
                          <StatusBadge status={run.status} />
                          {run.status === "running" && <LiveBadge />}
                        </span>
                      </td>
                      <td className="table__num">
                        {typeof run.totals.events === "number" ? run.totals.events : "—"}
                      </td>
                      <td className="table__num">
                        {typeof run.totals.cost_usd === "number"
                          ? `$${run.totals.cost_usd.toFixed(2)}`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card__head">
            <h2 className="card__title">Recent incidents</h2>
            <Link to="/incidents" className="chip">
              View all <IconArrowRight />
            </Link>
          </div>
          {stats.recent_detections.length === 0 ? (
            <div className="empty-state">No detections raised.</div>
          ) : (
            <div>
              {stats.recent_detections.map((detection) => (
                <div className="incident" key={detection.detection_id}>
                  <span
                    className="incident__icon"
                    style={{
                      color: SEVERITY_COLOR[detection.severity] ?? "var(--text-muted)",
                    }}
                  >
                    <IconAlert size={14} />
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <div className="incident__title">{detectionTitle(detection)}</div>
                    <div className="incident__meta">
                      <Link to={`/runs/${detection.run_id}`}>{detection.run_id.slice(0, 18)}…</Link>{" "}
                      · {detection.severity}
                    </div>
                  </span>
                  <span className="incident__when">{relativeTime(detection.raised_at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
