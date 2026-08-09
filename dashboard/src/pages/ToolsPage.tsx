import { useState } from "react";

import type { ToolStat } from "../api/runApi";
import { useTools } from "../hooks/useCatalog";

type SortKey = "calls" | "errors" | "avg_latency_ms" | "p95_latency_ms";

function sortIndicator(active: boolean, direction: "asc" | "desc"): string {
  if (!active) return "";
  return direction === "desc" ? " ▼" : " ▲";
}

// Per-tool rollup from GET /v1/tools — derived server-side from recent
// tool.call events, so the numbers match what the timeline shows.
// Sortable client-side: the endpoint returns its entire window in one
// response (no pagination), so a client sort is always fully correct here.
export default function ToolsPage() {
  const { data, isLoading, isError, error } = useTools();
  const [sortKey, setSortKey] = useState<SortKey>("calls");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");

  if (isLoading && !data) {
    return (
      <div className="page">
        <p className="muted">Loading tools&hellip;</p>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load tools: {error instanceof Error ? error.message : String(error)}
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

  const tools: ToolStat[] = [...data.tools].sort((a, b) => {
    const delta = a[sortKey] - b[sortKey];
    return direction === "desc" ? -delta : delta;
  });

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Tools</h1>
        <span className="page__sub">
          across the last {data.window_events} tool call
          {data.window_events === 1 ? "" : "s"}
        </span>
      </div>

      <div className="card">
        {tools.length === 0 ? (
          <div className="empty-state">
            No tool calls recorded yet. Any function wrapped in{" "}
            <code className="mono">@trace_tool</code> (or invoked through an instrumented framework)
            shows up here.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Side effect</th>
                  <th
                    className="table__num"
                    onClick={() => toggleSort("calls")}
                    style={{ cursor: "pointer" }}
                  >
                    Calls{sortIndicator(sortKey === "calls", direction)}
                  </th>
                  <th
                    className="table__num"
                    onClick={() => toggleSort("errors")}
                    style={{ cursor: "pointer" }}
                  >
                    Errors{sortIndicator(sortKey === "errors", direction)}
                  </th>
                  <th
                    className="table__num"
                    onClick={() => toggleSort("avg_latency_ms")}
                    style={{ cursor: "pointer" }}
                  >
                    Avg latency{sortIndicator(sortKey === "avg_latency_ms", direction)}
                  </th>
                  <th
                    className="table__num"
                    onClick={() => toggleSort("p95_latency_ms")}
                    style={{ cursor: "pointer" }}
                  >
                    P95 latency{sortIndicator(sortKey === "p95_latency_ms", direction)}
                  </th>
                  <th>Last used</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((tool) => (
                  <tr key={tool.tool_name}>
                    <td className="table__mono">{tool.tool_name}</td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          color:
                            tool.side_effect_class === "read"
                              ? "var(--text-muted)"
                              : "var(--status-warning)",
                        }}
                      >
                        <span className="badge__dot" />
                        {tool.side_effect_class}
                      </span>
                    </td>
                    <td className="table__num">{tool.calls}</td>
                    <td
                      className="table__num"
                      style={{
                        color: tool.errors > 0 ? "var(--status-critical)" : undefined,
                      }}
                    >
                      {tool.errors}
                    </td>
                    <td className="table__num">{tool.avg_latency_ms.toFixed(2)}ms</td>
                    <td className="table__num">{tool.p95_latency_ms.toFixed(2)}ms</td>
                    <td className="muted">
                      {tool.last_used ? new Date(tool.last_used).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
