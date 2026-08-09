import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getHealthz } from "../api/runApi";
import { useProjects } from "../hooks/useCatalog";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { RANGE_OPTIONS, useFilters } from "../lib/filters";
import { usePreferences } from "../lib/preferences";

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8420";

type Section = "appearance" | "preferences" | "notifications" | "security" | "application";

const SECTIONS: { id: Section; label: string }[] = [
  { id: "appearance", label: "Appearance" },
  { id: "preferences", label: "Preferences" },
  { id: "notifications", label: "Notifications" },
  { id: "security", label: "Security & Privacy" },
  { id: "application", label: "Application" },
];

function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          className={
            value === option.value ? "segmented__btn segmented__btn--active" : "segmented__btn"
          }
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  id,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  id: string;
}) {
  return (
    <label className="toggle-row" htmlFor={id}>
      <span>{label}</span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        className={checked ? "toggle toggle--on" : "toggle"}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle__thumb" />
      </button>
    </label>
  );
}

function AppearanceSection() {
  const { theme, setTheme, density, setDensity } = usePreferences();
  return (
    <div className="card">
      <div className="card__head">
        <h2 className="card__title">Appearance</h2>
      </div>
      <div className="stack" style={{ gap: 18 }}>
        <label className="field">
          <span className="field__label">Theme</span>
          <SegmentedControl
            value={theme}
            onChange={setTheme}
            options={[
              { value: "dark", label: "Dark" },
              { value: "light", label: "Light" },
            ]}
          />
        </label>
        <label className="field">
          <span className="field__label">Density</span>
          <SegmentedControl
            value={density}
            onChange={setDensity}
            options={[
              { value: "comfortable", label: "Comfortable" },
              { value: "compact", label: "Compact" },
            ]}
          />
        </label>
      </div>
    </div>
  );
}

function PreferencesSection() {
  const {
    defaultProject,
    setDefaultProject,
    defaultRangeLabel,
    setDefaultRangeLabel,
    liveUpdatesEnabled,
    setLiveUpdatesEnabled,
  } = usePreferences();
  const { data: projectsPage } = useProjects();

  return (
    <div className="card">
      <div className="card__head">
        <h2 className="card__title">Preferences</h2>
      </div>
      <div className="stack" style={{ gap: 14 }}>
        <label className="field">
          <span className="field__label">Default project</span>
          <span className="muted" style={{ fontSize: 12 }}>
            What Overview opens to on a fresh load — not the current live filter, which is set from
            the topbar and resets on reload.
          </span>
          <select
            className="select"
            value={defaultProject ?? ""}
            onChange={(event) => setDefaultProject(event.target.value || undefined)}
          >
            <option value="">All projects</option>
            {(projectsPage?.projects ?? []).map((entry) => (
              <option key={entry.project_id} value={entry.project_id}>
                {entry.name} ({entry.runs})
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field__label">Default time range</span>
          <select
            className="select"
            value={defaultRangeLabel}
            onChange={(event) => setDefaultRangeLabel(event.target.value)}
          >
            {RANGE_OPTIONS.map((option) => (
              <option key={option.label} value={option.label}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <Toggle
          id="live-updates-toggle"
          label="Live updates"
          checked={liveUpdatesEnabled}
          onChange={setLiveUpdatesEnabled}
        />
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          Off stops the SSE subscription entirely — views only refresh when you navigate, instead of
          the moment an event lands.
        </p>
      </div>
    </div>
  );
}

function NotificationsSection() {
  const {
    desktopNotificationsEnabled,
    setDesktopNotificationsEnabled,
    notifyOnCriticalDetection,
    setNotifyOnCriticalDetection,
    notifyOnPolicyDenial,
    setNotifyOnPolicyDenial,
  } = usePreferences();
  const [permissionDenied, setPermissionDenied] = useState(false);
  const notificationsSupported = typeof Notification !== "undefined";

  async function handleToggle(next: boolean) {
    if (!next) {
      setDesktopNotificationsEnabled(false);
      return;
    }
    if (!notificationsSupported) return;
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      setPermissionDenied(false);
      setDesktopNotificationsEnabled(true);
    } else {
      setPermissionDenied(true);
      setDesktopNotificationsEnabled(false);
    }
  }

  return (
    <div className="card">
      <div className="card__head">
        <h2 className="card__title">Notifications</h2>
      </div>
      {!notificationsSupported ? (
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          This browser doesn't support desktop notifications.
        </p>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          <Toggle
            id="desktop-notifications-toggle"
            label="Desktop notifications"
            checked={desktopNotificationsEnabled}
            onChange={(checked) => void handleToggle(checked)}
          />
          {permissionDenied && (
            <p style={{ fontSize: 12.5, margin: 0, color: "var(--status-critical)" }}>
              Browser permission was denied. Re-enable notifications for this site in your browser's
              site settings, then try again.
            </p>
          )}
          <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
            Fires a real OS-level notification the moment a matching event streams in — the same
            live connection every other view uses, not a poll.
          </p>

          <div
            className="stack"
            style={{ gap: 10, opacity: desktopNotificationsEnabled ? 1 : 0.5 }}
          >
            <Toggle
              id="notify-critical-toggle"
              label="Critical incidents"
              checked={notifyOnCriticalDetection}
              onChange={setNotifyOnCriticalDetection}
            />
            <Toggle
              id="notify-denial-toggle"
              label="Policy denials"
              checked={notifyOnPolicyDenial}
              onChange={setNotifyOnPolicyDenial}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function SecuritySection() {
  return (
    <div className="card">
      <div className="card__head">
        <h2 className="card__title">Security & Privacy</h2>
      </div>
      <div className="stack" style={{ gap: 12 }}>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          There is nothing user-editable here — this section states the actual posture rather than
          hiding it behind controls that would not do anything.
        </p>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--text-secondary)" }}>
          <li>
            Ingest and policy-evaluation endpoints require a bearer API key, configured server-side
            (<code className="mono">TRAZO_API_KEY</code>) — not editable from this dashboard.
          </li>
          <li>
            Query and dashboard endpoints are intentionally unauthenticated, designed for a
            localhost or private-network deployment, not the public internet (ADR-009).
          </li>
          <li>
            There are no user accounts, teams, or workspaces — this deployment is not multi-tenant.
          </li>
        </ul>
      </div>
    </div>
  );
}

function ApplicationSection() {
  const { project } = useFilters();
  const { liveUpdatesEnabled } = usePreferences();
  const { connected, streaming } = useLiveRefresh(project, { enabled: liveUpdatesEnabled });
  const { data: healthz } = useQuery({
    queryKey: ["healthz"],
    queryFn: getHealthz,
    staleTime: 60_000,
  });

  return (
    <div className="card">
      <div className="card__head">
        <h2 className="card__title">Application</h2>
      </div>
      <div className="kv">
        <span className="kv__k">Control plane</span>
        <span className="kv__v mono" style={{ fontSize: 12 }}>
          {API_BASE}
        </span>
        <span className="kv__k">Version</span>
        <span className="kv__v mono" style={{ fontSize: 12 }}>
          {healthz?.version ?? "—"}
        </span>
        <span className="kv__k">Live stream</span>
        <span
          className="kv__v"
          style={{
            color: liveUpdatesEnabled
              ? connected
                ? "var(--status-good)"
                : "var(--status-critical)"
              : "var(--text-muted)",
          }}
        >
          {liveUpdatesEnabled
            ? connected
              ? streaming
                ? "receiving events"
                : "connected"
              : "disconnected"
            : "off (Preferences)"}
        </span>
        <span className="kv__k">Refresh model</span>
        <span className="kv__v">SSE-driven</span>
      </div>
      <p className="muted" style={{ fontSize: 12.5, marginTop: 12, marginBottom: 0 }}>
        Views re-read when the server streams a new event, not on a timer. If the stream drops, data
        stays as-of the last event received until you navigate.
      </p>
    </div>
  );
}

export default function SettingsPage() {
  const [active, setActive] = useState<Section>("appearance");

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Settings</h1>
        <span className="page__sub">appearance, preferences, and connection status</span>
      </div>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          {SECTIONS.map((section) => (
            <button
              key={section.id}
              type="button"
              className={
                active === section.id
                  ? "settings-nav__item settings-nav__item--active"
                  : "settings-nav__item"
              }
              onClick={() => setActive(section.id)}
            >
              {section.label}
            </button>
          ))}
        </nav>

        <div>
          {active === "appearance" && <AppearanceSection />}
          {active === "preferences" && <PreferencesSection />}
          {active === "notifications" && <NotificationsSection />}
          {active === "security" && <SecuritySection />}
          {active === "application" && <ApplicationSection />}
        </div>
      </div>
    </div>
  );
}
