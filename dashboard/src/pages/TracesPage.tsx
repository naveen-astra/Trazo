import EventFeedPage from "./EventFeedPage";

export default function TracesPage() {
  return (
    <EventFeedPage
      title="Traces"
      subtitle="newest events across every run"
      emptyMessage="No events recorded yet."
    />
  );
}
