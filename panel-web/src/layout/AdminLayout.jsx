import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Moon, Sun } from "lucide-react";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";
import { DialogHost } from "../ui";
import { BottomNav } from "./BottomNav";
import { Sidebar } from "./Sidebar";
import { titleFor } from "./navigation";

export function AdminLayout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const { admin, logout } = useSession();
  const { theme, toggle } = useTheme();

  // Переход по маршруту закрывает мобильное меню: иначе лист остаётся
  // поверх только что открытой страницы.
  useEffect(() => setMenuOpen(false), [location.pathname]);

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
            <span className="ax-live-badge">
              <span className="ax-live-dot" />
              Данные живые
            </span>
          </div>

          <div className="ax-content">
            <Outlet />
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
