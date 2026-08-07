import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

// Shared dashboard filters: which project, and how far back. Both are
// real query parameters the API honours (GET /v1/stats?project=&days=),
// not client-side slicing — so the numbers a filter produces are the
// server's, same as every other figure on the page.

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
  const [project, setProject] = useState<string | undefined>(undefined);
  // 30 days by default: wide enough that a fresh install with a few days
  // of runs still shows a trend line, narrow enough to mean something.
  const [range, setRange] = useState<RangeOption>(RANGE_OPTIONS[2]!);

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
