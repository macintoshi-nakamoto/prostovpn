import { NavLink } from "react-router-dom";
import { LogOut } from "lucide-react";
import { NAV_GROUPS } from "./navigation";

export function Sidebar({ open, onNavigate, admin, onLogout }) {
  return (
    <aside className={`ax-sidebar${open ? " open" : ""}`}>
      {/* Ручка и заголовок видны только на телефоне, где сайдбар — нижний лист. */}
      <div className="ax-sheet-handle" aria-hidden="true" />
      <div className="ax-sheet-title">Разделы</div>

      {/* Знак, а не набранное имя: в админку заходят с того же сайта, и один
          и тот же логотип на обоих концах избавляет от вопроса «туда ли я
          попал». Путь с base — панель живёт на /admin/. */}
      <div className="ax-brand">
        <img className="ax-brand-logo" src={`${import.meta.env.BASE_URL}logo-v2.png`} alt="PROSTO" />
        <span className="ax-brand-sub">панель</span>
      </div>

      <nav className="ax-nav">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div className="ax-nav-group-label">{group.label}</div>
            {group.items.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => `ax-nav-item${isActive ? " active" : ""}`}
                onClick={onNavigate}
              >
                <Icon size={17} />
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="ax-sidebar-foot">
        <span>{admin?.login || "admin"}</span>
        <button className="gd-btn ghost sm" style={{ marginLeft: "auto" }} onClick={onLogout}>
          <LogOut size={14} />
          Выйти
        </button>
      </div>
    </aside>
  );
}
