import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import App from "./App";
import { AuthGate } from "./lib/auth";
import { FiltersProvider } from "./lib/filters";
import { PreferencesProvider } from "./lib/preferences";
import AgentsPage from "./pages/AgentsPage";
import IncidentsPage from "./pages/IncidentsPage";
import LogsPage from "./pages/LogsPage";
import ModelsPage from "./pages/ModelsPage";
import OverviewPage from "./pages/OverviewPage";
import PolicyPage from "./pages/PolicyPage";
import ReplayIndexPage from "./pages/ReplayIndexPage";
import ReplayStepperPage from "./pages/ReplayStepperPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsPage from "./pages/RunsPage";
import SettingsPage from "./pages/SettingsPage";
import ToolsPage from "./pages/ToolsPage";
import TracesPage from "./pages/TracesPage";
import "./index.css";

const queryClient = new QueryClient();

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "runs/:runId", element: <RunDetailPage /> },
      { path: "runs/:runId/replay", element: <ReplayStepperPage /> },
      { path: "traces", element: <TracesPage /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "models", element: <ModelsPage /> },
      { path: "replay", element: <ReplayIndexPage /> },
      { path: "logs", element: <LogsPage /> },
      { path: "incidents", element: <IncidentsPage /> },
      { path: "policy", element: <PolicyPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("missing #root element");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* Preferences outermost: FiltersProvider reads its persisted
          defaultProject/defaultRangeLabel to seed the live filter state
          below it. Both live above the router so the topbar's project
          selector and every page share one source of truth. */}
      <PreferencesProvider>
        {/* Inside Preferences so the sign-in page follows the saved
            theme; outside the router so no route renders, and no panel
            fetches, until the session is accepted. */}
        <AuthGate>
          <FiltersProvider>
            <RouterProvider router={router} />
          </FiltersProvider>
        </AuthGate>
      </PreferencesProvider>
    </QueryClientProvider>
  </StrictMode>,
);
