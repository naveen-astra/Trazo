// An event's place in its run is (seq, sub_seq): `seq` is assigned by the
// SDK, and a server event (a detection, a policy decision) shares the seq
// of the agent event it follows, ordered under it by sub_seq 1, 2, ...
// Sorting or de-duplicating on `seq` alone would scramble or drop those.
// `event_id` is the unique key.

interface Positioned {
  seq: number;
  sub_seq?: number;
}

export function compareEvents(a: Positioned, b: Positioned): number {
  return a.seq - b.seq || (a.sub_seq ?? 0) - (b.sub_seq ?? 0);
}

/** "12" for an agent event, "12.1" for a server event recorded after it. */
export function formatPosition(event: Positioned): string {
  return event.sub_seq ? `${event.seq}.${event.sub_seq}` : `${event.seq}`;
}
