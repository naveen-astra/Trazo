// Placeholder Runs page (TRZ-P0-04). The real run list — rollups, status,
// live badge — is TRZ-P2-07 and consumes GET /v1/runs per API_SPEC.md.
export default function RunsPage() {
  return (
    <section>
      <h1>Runs</h1>
      <p>
        No runs yet. The run list lands in Phase 2 (TRZ-P2-07), backed by the query API. This
        placeholder exists so the compose stack serves a real page from day one.
      </p>
    </section>
  );
}
