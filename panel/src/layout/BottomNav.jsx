import { NavLink, useLocation } from "react-router-dom";
import { LayoutGrid } from "lucide-react";
import { BOTTOM_NAV } from "./navigation";

export function BottomNav({ menuOpen, onToggleMenu, onNavigate }) {
  const location = useLocation();
  const count = BOTTOM_NAV.length + 1;

  const routeIndex = BOTTOM_NAV.findIndex(
    (item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`),
  );

  const activeIndex = menuOpen ? BOTTOM_NAV.length : routeIndex;

  return (
    <nav className="ax-bottombar" aria-label="Мобильная навигация">
      {activeIndex >= 0 && (
        <div
          className="ax-bb-pill"
          style={{ width: `${100 / count}%`, transform: `translateX(${activeIndex * 100}%)` }}
          aria-hidden="true"
        >
          <span key={activeIndex} className="ax-bb-glass" />
        </div>
      )}

      {BOTTOM_NAV.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) => `ax-bb-item${isActive && !menuOpen ? " active" : ""}`}
          onClick={onNavigate}
        >
          <span className="ax-bb-ico">
            <Icon size={21} />
          </span>
          <span className="ax-bb-label">{label}</span>
        </NavLink>
      ))}

      <button
        className={`ax-bb-item${menuOpen ? " active" : ""}`}
        onClick={onToggleMenu}
        aria-label="Все разделы"
      >
        <span className="ax-bb-ico">
          <LayoutGrid size={21} />
        </span>
        <span className="ax-bb-label">Меню</span>
      </button>
    </nav>
  );
}
