import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { LogOut } from "lucide-react";
import { NAV_GROUPS } from "./navigation";

/**
 * Скользящая «капля» под активным пунктом — как переключатель вкладок в
 * кабинете: подложка не перерисовывается, а переезжает между разделами.
 * Меряем по DOM после отрисовки, чтобы переезд шёл от старого места.
 */
function useNavPill(pathname) {
  const ref = useRef(null);
  const [pill, setPill] = useState(null);

  useLayoutEffect(() => {
    const nav = ref.current;
    if (!nav) return undefined;

    const measure = () => {
      const active = nav.querySelector(".ax-nav-item.active");
      if (!active) return setPill(null);
      const box = nav.getBoundingClientRect();
      const spot = active.getBoundingClientRect();
      if (!spot.height) return setPill(null);
      return setPill({ top: spot.top - box.top + nav.scrollTop, height: spot.height });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(nav);
    window.addEventListener("resize", measure);
    if (document.fonts?.ready) document.fonts.ready.then(measure).catch(() => {});
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [pathname]);

  return [ref, pill];
}

export function Sidebar({ open, onNavigate, admin, onLogout }) {
  const location = useLocation();
  const [navRef, pill] = useNavPill(location.pathname);

  return (
    <aside className={`ax-sidebar${open ? " open" : ""}`}>
      <div className="ax-sheet-handle" aria-hidden="true" />
      <div className="ax-sheet-title">Разделы</div>

      <div className="ax-brand">
        <img className="ax-brand-logo" src={`${import.meta.env.BASE_URL}logo-v3.png`} alt="PROSTO" />
        <span className="ax-brand-sub">панель</span>
      </div>

      <nav className="ax-nav" ref={navRef}>
        {pill && (
          <span
            className="ax-nav-pill"
            aria-hidden="true"
            style={{ transform: `translateY(${pill.top}px)`, height: `${pill.height}px` }}
          />
        )}
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
