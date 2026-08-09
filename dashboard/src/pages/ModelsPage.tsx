import { useModels } from "../hooks/useCatalog";

// Per-(provider, model) rollup from GET /v1/models — the standard
// LLM-ops "where is the money going" view, derived server-side from
// recent llm.call events. Sorted by spend (the API's own default order),
// not volume, since cost is what this page exists to answer.
export default function ModelsPage() {
  const { data, isLoading, isError, error } = useModels();

  if (isLoading && !data) {
    return (
      <div className="page">
        <p className="muted">Loading models&hellip;</p>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load models: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Models</h1>
        <span className="page__sub">
          across the last {data.window_events} LLM call{data.window_events === 1 ? "" : "s"},
          costliest first
        </span>
      </div>

      <div className="card">
        {data.models.length === 0 ? (
          <div className="empty-state">
            No LLM calls recorded yet. Every <code className="mono">llm.call</code> event carries
            provider, model, and cost — they roll up here the moment one lands.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Model</th>
                  <th className="table__num">Calls</th>
                  <th className="table__num">Cost</th>
                  <th className="table__num">Tokens in</th>
                  <th className="table__num">Tokens out</th>
                  <th className="table__num">Avg latency</th>
                  <th className="table__num">P50</th>
                  <th className="table__num">P95</th>
                  <th>Last used</th>
                </tr>
              </thead>
              <tbody>
                {data.models.map((model) => (
                  <tr key={`${model.provider}/${model.model}`}>
                    <td className="muted">{model.provider}</td>
                    <td className="table__mono">{model.model}</td>
                    <td className="table__num">{model.calls}</td>
                    <td className="table__num">${model.cost_usd.toFixed(4)}</td>
                    <td className="table__num">{model.tokens_in.toLocaleString()}</td>
                    <td className="table__num">{model.tokens_out.toLocaleString()}</td>
                    <td className="table__num">{model.avg_latency_ms.toFixed(0)}ms</td>
                    <td className="table__num">{model.p50_latency_ms.toFixed(0)}ms</td>
                    <td className="table__num">{model.p95_latency_ms.toFixed(0)}ms</td>
                    <td className="muted">
                      {model.last_used ? new Date(model.last_used).toLocaleString() : "—"}
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
