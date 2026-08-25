import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n/index.jsx";
import { NAV_ICONS } from "./NavIcons.jsx";

function usePill(tab) {
  const ref = useRef(null);
  const [pill, setPill] = useState(null);

  useLayoutEffect(() => {
    const nav = ref.current;
    if (!nav) return undefined;

    const measure = () => {
      const active = nav.querySelector('[data-active="true"]');
      const spot = active?.getBoundingClientRect();

      if (!spot || spot.width === 0) return setPill(null);
      const box = nav.getBoundingClientRect();
      return setPill({ left: spot.left - box.left, width: spot.width });
    };

    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(nav);

    for (const child of nav.children) observer.observe(child);

    window.addEventListener("resize", measure);

    if (document.fonts?.ready) document.fonts.ready.then(measure).catch(() => {});

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [tab]);

  return [ref, pill];
}

export function CabinetNav({ tabs, tab, hrefOf }) {
  const { t } = useI18n();
  const [ref, pill] = usePill(tab);

  return (
    <nav className="ac-tabs" ref={ref} aria-label={t("account.navLabel")}>
      {pill && (
        <span
          className="ac-pill"
          aria-hidden="true"
          style={{ transform: `translateX(${pill.left}px)`, width: `${pill.width}px` }}
        />
      )}
      {tabs.map((id) => (
        <Link
          key={id}
          to={hrefOf(id)}
          replace={tab === id}
          data-active={tab === id ? "true" : undefined}
          aria-current={tab === id ? "page" : undefined}
        >
          {t(`account.tabs.${id}`)}
        </Link>
      ))}
    </nav>
  );
}

export function CabinetBottomNav({ tabs, tab, hrefOf }) {
  const { t } = useI18n();

  return (
    <nav className="ac-bottom" aria-label={t("account.navLabel")}>
      {tabs.map((id) => {
        const Icon = NAV_ICONS[id];
        return (
          <Link
            key={id}
            to={hrefOf(id)}
            replace={tab === id}
            className={tab === id ? "active" : undefined}
            aria-current={tab === id ? "page" : undefined}
          >
            {Icon ? <Icon /> : null}
            <span>{t(`account.tabs.${id}`)}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function useScrolled(threshold = 8) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const check = () => setScrolled(window.scrollY > threshold);
    check();
    window.addEventListener("scroll", check, { passive: true });
    return () => window.removeEventListener("scroll", check);
  }, [threshold]);

  return scrolled;
}
