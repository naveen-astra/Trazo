import { Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Trazo</span>
        <span className="app-subtitle">observability · replay · governance</span>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
