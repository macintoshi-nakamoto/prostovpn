import { useEffect, useRef } from "react";
import { Sheet } from "./Sheet.jsx";
import { tmaHaptic } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Как сменить регион App Store, чтобы поставить AmneziaVPN, Happ и
 * остальное. Один лист на всех: сам всплывает при первом заходе в кабинет
 * (и тихо уходит, если его не трогать), и открывается кнопкой рядом с
 * ключом для iPhone.
 */

export const APPSTORE_NEVER_KEY = "prosto_appstore_never";
export const APPSTORE_SHOWN_KEY = "prosto_appstore_shown";

// Сколько висит само по себе, если человек его не трогает.
const AUTO_HIDE_MS = 14000;

export function appStoreAutoAllowed() {
  try {
    if (localStorage.getItem(APPSTORE_NEVER_KEY) === "1") return false;
    if (sessionStorage.getItem(APPSTORE_SHOWN_KEY) === "1") return false;
    return true;
  } catch {
    return false;
  }
}

export function markAppStoreShown() {
  try {
    sessionStorage.setItem(APPSTORE_SHOWN_KEY, "1");
  } catch {}
}

export function AppStoreSheet({ open, auto = false, onClose }) {
  const { t, raw } = useI18n();
  const timer = useRef(null);

  // Автопоказ уходит сам: держим лист, пока человек читает, и убираем,
  // если он так и не тронул экран. Открытый кнопкой — висит, пока не закроют.
  useEffect(() => {
    if (!open || !auto) return undefined;
    timer.current = setTimeout(() => onClose?.(), AUTO_HIDE_MS);
    return () => clearTimeout(timer.current);
  }, [open, auto, onClose]);

  const never = () => {
    tmaHaptic("light");
    try {
      localStorage.setItem(APPSTORE_NEVER_KEY, "1");
    } catch {}
    onClose?.();
  };

  const steps = raw("appstore.steps");

  return (
    <Sheet open={open} title={t("appstore.title")} sub={t("appstore.lead")} onClose={onClose}>
      <div className="as">
        <ol className="as-steps">
          {(Array.isArray(steps) ? steps : []).map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        <p className="as-note">{t("appstore.note")}</p>
        <button
          type="button"
          className="ap-cta su-cta"
          onClick={() => {
            tmaHaptic("light");
            onClose?.();
          }}
        >
          {t("appstore.ok")}
        </button>
        {auto && (
          <button type="button" className="as-never" onClick={never}>
            {t("appstore.never")}
          </button>
        )}
      </div>
    </Sheet>
  );
}
