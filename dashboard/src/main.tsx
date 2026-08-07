import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import App from "./App";
import { FiltersProvider } from "./lib/filters";
import AgentsPage from "./pages/AgentsPage";
import IncidentsPage from "./pages/IncidentsPage";
import LogsPage from "./pages/LogsPage";
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
      {/* Filters live above the router so the topbar's project selector
          and every page share one source of truth. */}
      <FiltersProvider>
        <RouterProvider router={router} />
      </FiltersProvider>
    </QueryClientProvider>
  </StrictMode>,
);
