import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

// Every *persisted* user preference lives here, one localStorage key per
// field — distinct from lib/filters.tsx's FiltersProvider, which owns only
// the live, in-session, non-persisted project/range filter (it resets on
// reload by design; these do not). Settings writes here; App.tsx and
// FiltersProvider both read from here to seed their own state.

export type Theme = "dark" | "light";
export type Density = "comfortable" | "compact";

const STORAGE_KEYS = {
  theme: "trazo-theme", // unchanged key: this preference already existed
  density: "trazo-pref-density",
  defaultProject: "trazo-pref-default-project",
  defaultRangeLabel: "trazo-pref-default-range",
  liveUpdatesEnabled: "trazo-pref-live-updates",
  desktopNotificationsEnabled: "trazo-pref-desktop-notifications",
  notifyOnCriticalDetection: "trazo-pref-notify-critical",
  notifyOnPolicyDenial: "trazo-pref-notify-denial",
} as const;

function readString<T extends string>(key: string, fallback: T): T {
  const stored = localStorage.getItem(key);
  return (stored as T | null) ?? fallback;
}

function readBool(key: string, fallback: boolean): boolean {
  const stored = localStorage.getItem(key);
  if (stored === null) return fallback;
  return stored === "true";
}

interface Preferences {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  density: Density;
  setDensity: (density: Density) => void;
  /** undefined = "All projects" is the default landing view. */
  defaultProject: string | undefined;
  setDefaultProject: (project: string | undefined) => void;
  defaultRangeLabel: string;
  setDefaultRangeLabel: (label: string) => void;
  liveUpdatesEnabled: boolean;
  setLiveUpdatesEnabled: (enabled: boolean) => void;
  desktopNotificationsEnabled: boolean;
  setDesktopNotificationsEnabled: (enabled: boolean) => void;
  notifyOnCriticalDetection: boolean;
  setNotifyOnCriticalDetection: (enabled: boolean) => void;
  notifyOnPolicyDenial: boolean;
  setNotifyOnPolicyDenial: (enabled: boolean) => void;
}

const PreferencesContext = createContext<Preferences | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => readString(STORAGE_KEYS.theme, "dark"));
  const [density, setDensityState] = useState<Density>(() =>
    readString(STORAGE_KEYS.density, "comfortable"),
  );
  const [defaultProject, setDefaultProjectState] = useState<string | undefined>(
    () => localStorage.getItem(STORAGE_KEYS.defaultProject) ?? undefined,
  );
  const [defaultRangeLabel, setDefaultRangeLabelState] = useState<string>(() =>
    readString(STORAGE_KEYS.defaultRangeLabel, "Last 30 days"),
  );
  const [liveUpdatesEnabled, setLiveUpdatesEnabledState] = useState<boolean>(() =>
    readBool(STORAGE_KEYS.liveUpdatesEnabled, true),
  );
  const [desktopNotificationsEnabled, setDesktopNotificationsEnabledState] = useState<boolean>(() =>
    readBool(STORAGE_KEYS.desktopNotificationsEnabled, false),
  );
  const [notifyOnCriticalDetection, setNotifyOnCriticalDetectionState] = useState<boolean>(() =>
    readBool(STORAGE_KEYS.notifyOnCriticalDetection, true),
  );
  const [notifyOnPolicyDenial, setNotifyOnPolicyDenialState] = useState<boolean>(() =>
    readBool(STORAGE_KEYS.notifyOnPolicyDenial, true),
  );

  // Theme and density apply as attributes on <html> — index.css's
  // [data-theme]/[data-density] selectors key off exactly these.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(STORAGE_KEYS.theme, theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    localStorage.setItem(STORAGE_KEYS.density, density);
  }, [density]);

  function setDefaultProject(project: string | undefined) {
    setDefaultProjectState(project);
    if (project) {
      localStorage.setItem(STORAGE_KEYS.defaultProject, project);
    } else {
      localStorage.removeItem(STORAGE_KEYS.defaultProject);
    }
  }

  function setDefaultRangeLabel(label: string) {
    setDefaultRangeLabelState(label);
    localStorage.setItem(STORAGE_KEYS.defaultRangeLabel, label);
  }

  function setLiveUpdatesEnabled(enabled: boolean) {
    setLiveUpdatesEnabledState(enabled);
    localStorage.setItem(STORAGE_KEYS.liveUpdatesEnabled, String(enabled));
  }

  function setDesktopNotificationsEnabled(enabled: boolean) {
    setDesktopNotificationsEnabledState(enabled);
    localStorage.setItem(STORAGE_KEYS.desktopNotificationsEnabled, String(enabled));
  }

  function setNotifyOnCriticalDetection(enabled: boolean) {
    setNotifyOnCriticalDetectionState(enabled);
    localStorage.setItem(STORAGE_KEYS.notifyOnCriticalDetection, String(enabled));
  }

  function setNotifyOnPolicyDenial(enabled: boolean) {
    setNotifyOnPolicyDenialState(enabled);
    localStorage.setItem(STORAGE_KEYS.notifyOnPolicyDenial, String(enabled));
  }

  const value = useMemo<Preferences>(
    () => ({
      theme,
      setTheme: setThemeState,
      density,
      setDensity: setDensityState,
      defaultProject,
      setDefaultProject,
      defaultRangeLabel,
      setDefaultRangeLabel,
      liveUpdatesEnabled,
      setLiveUpdatesEnabled,
      desktopNotificationsEnabled,
      setDesktopNotificationsEnabled,
      notifyOnCriticalDetection,
      setNotifyOnCriticalDetection,
      notifyOnPolicyDenial,
      setNotifyOnPolicyDenial,
    }),
    [
      theme,
      density,
      defaultProject,
      defaultRangeLabel,
      liveUpdatesEnabled,
      desktopNotificationsEnabled,
      notifyOnCriticalDetection,
      notifyOnPolicyDenial,
    ],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): Preferences {
  const value = useContext(PreferencesContext);
  if (!value) {
    throw new Error("usePreferences must be used inside <PreferencesProvider>");
  }
  return value;
}
