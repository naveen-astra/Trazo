import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { usePreferences } from "./preferences";

// Shared dashboard filters: which project, and how far back. Both are
// real query parameters the API honours (GET /v1/stats?project=&days=),
// not client-side slicing — so the numbers a filter produces are the
// server's, same as every other figure on the page.
//
// Live, in-session state only — resets on reload by design. The starting
// point on a fresh load comes from usePreferences()'s persisted
// defaultProject/defaultRangeLabel (Settings → Preferences); once loaded,
// clicking around here doesn't write back to that default.

export interface RangeOption {
  label: string;
  days?: number;
}

export const RANGE_OPTIONS: RangeOption[] = [
  { label: "Last 24 hours", days: 1 },
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "All time" },
];

interface Filters {
  project?: string;
  setProject: (project?: string) => void;
  range: RangeOption;
  setRange: (range: RangeOption) => void;
}

const FiltersContext = createContext<Filters | null>(null);

export function FiltersProvider({ children }: { children: ReactNode }) {
  const { defaultProject, defaultRangeLabel } = usePreferences();
  const [project, setProject] = useState<string | undefined>(() => defaultProject);
  // Falls back to 30 days (wide enough that a fresh install with a few
  // days of runs still shows a trend line) if the persisted default is
  // unset or names a range option that no longer exists.
  const [range, setRange] = useState<RangeOption>(
    () => RANGE_OPTIONS.find((r) => r.label === defaultRangeLabel) ?? RANGE_OPTIONS[2]!,
  );

  const value = useMemo(() => ({ project, setProject, range, setRange }), [project, range]);

  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>;
}

export function useFilters(): Filters {
  const value = useContext(FiltersContext);
  if (!value) {
    throw new Error("useFilters must be used inside <FiltersProvider>");
  }
  return value;
}
