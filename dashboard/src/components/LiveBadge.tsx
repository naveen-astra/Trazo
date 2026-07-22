/** Shown alongside StatusBadge for a currently-running run (TRZ-P2-07 DoD:
 * "live badge"). Separate from status: a run can be "running" whether or
 * not this dashboard happens to have a live SSE connection open to it. */
export default function LiveBadge() {
  return (
    <span className="live-badge">
      <span className="live-badge__dot" />
      LIVE
    </span>
  );
}
