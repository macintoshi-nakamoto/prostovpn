import { useI18n } from "../lib/i18n/index.jsx";
import { useTheme } from "../lib/theme.jsx";
import { isTma, tmaHaptic, tmaOpenTg } from "../lib/telegram.js";
import { SUPPORT_CHAT } from "../lib/contacts.js";
import "./controls.css";

const SUPPORT_TG = SUPPORT_CHAT;

function PlaneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path
        d="M21.6 3.1 2.9 10.6c-1 .4-.9 1.4 0 1.7l4.6 1.5 1.7 5.2c.3.9 1.2 1 1.8.3l2.5-2.7 4.7 3.5c.7.5 1.6.2 1.8-.7l3-14.7c.2-1-.6-1.7-1.4-1.6zM9 13.4l8.9-6.5c.3-.2.5.1.3.3l-7.1 6.9-.3 3.2-1.2-3.6z"
        fill="currentColor"
      />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="4.2" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M12 2.6v2.6M12 18.8v2.6M2.6 12h2.6M18.8 12h2.6" />
        <path d="M5.4 5.4l1.8 1.8M16.8 16.8l1.8 1.8M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8" />
      </g>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path
        d="M20.3 14.6A8.6 8.6 0 0 1 9.4 3.7a8.7 8.7 0 1 0 10.9 10.9z"
        fill="currentColor"
      />
    </svg>
  );
}

export function Controls() {
  const { lang, setLang, t } = useI18n();
  const { dark, toggle } = useTheme();

  return (
    <div className="ctl">
      <div
        className={`ctl-lang${lang === "en" ? " ctl-lang-en" : ""}`}
        role="group"
        aria-label={t("controls.language")}
      >
        <span className="ctl-thumb" aria-hidden="true" />
        <button
          type="button"
          className={lang === "ru" ? "active" : ""}
          aria-pressed={lang === "ru"}
          onClick={() => setLang("ru")}
        >
          RU
        </button>
        <button
          type="button"
          className={lang === "en" ? "active" : ""}
          aria-pressed={lang === "en"}
          onClick={() => setLang("en")}
        >
          EN
        </button>
      </div>

      <button
        type="button"
        className={`ctl-theme${dark ? " ctl-theme-dark" : ""}`}
        onClick={toggle}

        title={dark ? t("controls.themeToLight") : t("controls.themeToDark")}
        aria-label={dark ? t("controls.themeToLight") : t("controls.themeToDark")}
      >
        <span className="ctl-ic ctl-ic-sun">
          <SunIcon />
        </span>
        <span className="ctl-ic ctl-ic-moon">
          <MoonIcon />
        </span>
      </button>

      {isTma() && (
        <button
          type="button"
          className="ctl-theme ctl-sup"
          title={t("footer.support")}
          aria-label={t("footer.support")}
          onClick={() => {
            tmaHaptic("light");
            tmaOpenTg(SUPPORT_TG);
          }}
        >
          <PlaneIcon />
        </button>
      )}
    </div>
  );
}
