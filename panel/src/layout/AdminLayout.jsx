import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Moon, Sun } from "lucide-react";
import { ago } from "../lib/format";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";
import { DialogHost } from "../ui";
import { BottomNav } from "./BottomNav";
import { Sidebar } from "./Sidebar";
import { titleFor } from "./navigation";

const FreshnessContext = createContext(null);

export function useFreshness(data, error) {
  const report = useContext(FreshnessContext);
  useEffect(() => {
    if (!report || (!data && !error)) return;
    report({ at: Date.now(), ok: !error });
  }, [report, data, error]);
}

export function AdminLayout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [freshness, setFreshness] = useState(null);
  const location = useLocation();
  const { admin, logout } = useSession();
  const { theme, toggle } = useTheme();

  const report = useCallback((state) => setFreshness(state), []);

  useEffect(() => {
    setMenuOpen(false);

    setFreshness(null);
  }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [menuOpen]);

  return (
    <div className="ax-root">
      <DialogHost />
      <div className="ax-shell">
        {menuOpen && (
          <div className="ax-sidebar-overlay" onClick={() => setMenuOpen(false)} aria-hidden="true" />
        )}

        <Sidebar
          open={menuOpen}
          admin={admin}
          onNavigate={() => setMenuOpen(false)}
          onLogout={logout}
        />

        <main className="ax-main">
          <div className="ax-topbar">
            <div className="ax-topbar-title">{titleFor(location.pathname)}</div>
            <div className="ax-topbar-spacer" />
            <button
              type="button"
              className="ax-theme-toggle"
              onClick={toggle}
              title={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
              <span>{theme === "dark" ? "Светлая" : "Тёмная"}</span>
            </button>
            <FreshnessBadge state={freshness} />
          </div>

          <div className="ax-content">
            <FreshnessContext.Provider value={report}>
              <Outlet />
            </FreshnessContext.Provider>
          </div>
        </main>

        <BottomNav
          menuOpen={menuOpen}
          onToggleMenu={() => setMenuOpen((v) => !v)}
          onNavigate={() => setMenuOpen(false)}
        />
      </div>
    </div>
  );
}

function FreshnessBadge({ state }) {
  const [, redraw] = useState(0);

  useEffect(() => {
    if (!state) return undefined;
    const timer = setInterval(() => redraw((v) => v + 1), 5000);
    return () => clearInterval(timer);
  }, [state]);

  if (!state) return null;

  return (
    <span className="ax-live-badge">
      <span
        className="ax-live-dot"
        style={state.ok ? undefined : { background: "var(--ax-neg)", boxShadow: "none", animation: "none" }}
      />
      {state.ok ? `Обновлено ${ago(state.at)}` : "Обновить не удалось"}
    </span>
  );
}
