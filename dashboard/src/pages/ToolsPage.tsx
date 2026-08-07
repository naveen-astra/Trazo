import { useTools } from "../hooks/useCatalog";

// Per-tool rollup from GET /v1/tools — derived server-side from recent
// tool.call events, so the numbers match what the timeline shows.
export default function ToolsPage() {
  const { data, isLoading, isError, error } = useTools();

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
        {data.tools.length === 0 ? (
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
                  <th className="table__num">Calls</th>
                  <th className="table__num">Errors</th>
                  <th className="table__num">Avg latency</th>
                  <th>Last used</th>
                </tr>
              </thead>
              <tbody>
                {data.tools.map((tool) => (
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
