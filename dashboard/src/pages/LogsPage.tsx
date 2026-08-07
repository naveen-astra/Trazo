import EventFeedPage from "./EventFeedPage";

export default function LogsPage() {
  return (
    <EventFeedPage
      kind="sdk.diagnostic"
      title="Logs"
      subtitle="sdk.diagnostic events — the SDK reporting on itself"
      emptyMessage={
        <>
          No diagnostics recorded. The SDK emits <code className="mono">sdk.diagnostic</code> only
          when it has something to report (dropped events, degraded shipping) — an empty log here is
          the healthy case.
        </>
      }
    />
  );
}
