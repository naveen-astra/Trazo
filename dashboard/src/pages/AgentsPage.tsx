import { useState } from "react";

import type { AgentStat } from "../api/runApi";
import { useAgents } from "../hooks/useCatalog";

type SortKey = "events" | "runs";

function sortIndicator(active: boolean, direction: "asc" | "desc"): string {
  if (!active) return "";
  return direction === "desc" ? " ▼" : " ▲";
}

// Per-agent rollup from GET /v1/agents. The endpoint reports
// `unattributed_events` alongside on purpose: only an adapter that can
// name the acting agent sets agent_id (CrewAI's does, per role; the
// LangGraph adapter leaves it null because a graph node isn't an agent
// identity), so an empty table means "nothing attributed", not "nothing
// ran" — and this page says so rather than looking broken. Sortable
// client-side: the endpoint's whole window comes back in one response.
export default function AgentsPage() {
  const { data, isLoading, isError, error } = useAgents();
  const [sortKey, setSortKey] = useState<SortKey>("events");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");

  if (isLoading && !data) {
    return (
      <div className="page">
        <p className="muted">Loading agents&hellip;</p>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load agents: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDirection((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setDirection("desc");
    }
  }

  const agents: AgentStat[] = [...data.agents].sort((a, b) => {
    const delta = a[sortKey] - b[sortKey];
    return direction === "desc" ? -delta : delta;
  });

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Agents</h1>
        <span className="page__sub">
          attributed across the last {data.window_events} event
          {data.window_events === 1 ? "" : "s"}
        </span>
      </div>

      <div className="card">
        {agents.length === 0 ? (
          <div className="empty-state">
            No events carry an <code className="mono">agent_id</code> yet.
            {data.unattributed_events > 0 && (
              <>
                {" "}
                {data.unattributed_events} recent event
                {data.unattributed_events === 1 ? " was" : "s were"} recorded without one — the
                LangGraph adapter leaves it unset, since a graph node is a step, not an agent
                identity. CrewAI runs populate it per role.
              </>
            )}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th
                    className="table__num"
                    onClick={() => toggleSort("events")}
                    style={{ cursor: "pointer" }}
                  >
                    Events{sortIndicator(sortKey === "events", direction)}
                  </th>
                  <th
                    className="table__num"
                    onClick={() => toggleSort("runs")}
                    style={{ cursor: "pointer" }}
                  >
                    Runs{sortIndicator(sortKey === "runs", direction)}
                  </th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr key={agent.agent_id}>
                    <td className="table__mono">{agent.agent_id}</td>
                    <td className="table__num">{agent.events}</td>
                    <td className="table__num">{agent.runs}</td>
                    <td className="muted">
                      {agent.last_seen ? new Date(agent.last_seen).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {agents.length > 0 && data.unattributed_events > 0 && (
        <p className="muted" style={{ fontSize: 12.5 }}>
          {data.unattributed_events} of the last {data.window_events} events carried no agent_id and
          are not counted above.
        </p>
      )}
    </div>
  );
}
