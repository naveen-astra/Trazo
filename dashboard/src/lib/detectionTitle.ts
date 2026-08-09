const NAMED_DETECTORS: Record<string, string> = {
  loop: "Agent loop detected",
  budget: "Budget limit exceeded",
  thrash: "Tool thrashing detected",
  drift: "Goal drift detected",
};

/** Human-readable title for a detector name — shared by the Overview
 * incident feed and desktop notifications so both use the same wording. */
export function detectionTitle(detector: string): string {
  return NAMED_DETECTORS[detector] ?? `${detector} detected`;
}
