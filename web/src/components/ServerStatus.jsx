import { useEffect, useState } from "react";
import { Sheet } from "./Sheet.jsx";
import { Flag } from "./Flags.jsx";
import { api } from "../lib/api";
import { tmaHaptic } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";
import { BRAND } from "../lib/brand.js";

/**
 * Состояние узлов — полоска над содержимым кабинета.
 *
 * Данные те же, что видит админ в панели: живость отмечает обход за
 * трафиком, отдельной проверки нет. Когда всё работает, полоска тихая и
 * серая — она не должна каждый день сообщать хорошую новость крупно.
 * Что-то легло — окрашивается и называет страну: человек, у которого не
 * подключается, узнаёт причину раньше, чем напишет в поддержку.
 *
 * Обновляем раз в минуту и только когда вкладка на экране: страница
 * кабинета часто висит открытой сутками, и фоновый опрос в такой вкладке
 * бьёт по батарее ни за чем.
 */

const REFRESH_MS = 60_000;

/* Всё работает — зелёная галочка в кружке: живее плоской точки и сразу
   читается как «в порядке». Что-то легло — красный восклицательный знак,
   он ловит взгляд первым. */
export const OK_MARK = (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <circle cx="10" cy="10" r="9" fill="#34c759" />
    <path
      d="M5.8 10.3l2.7 2.7 5.7-6"
      fill="none"
      stroke="#fff"
      strokeWidth="2.1"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export const BAD_MARK = (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <circle cx="10" cy="10" r="9" fill="#ff453a" />
    <path d="M10 5.2v6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
    <circle cx="10" cy="14.4" r="1.2" fill="#fff" />
  </svg>
);

const CHEV = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9.6 6.4 15.2 12l-5.6 5.6" />
  </svg>
);

export function ServerStatus() {
  const { t } = useI18n();
  const [status, setStatus] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    let timer = null;

    const load = () => {
      if (document.hidden) return;
      api
        .status()
        .then((r) => alive && setStatus(r))
        .catch(() => {});
    };

    load();
    timer = setInterval(load, REFRESH_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, []);

  // Пока не ответили или узлов нет вовсе — полоски нет: пустая строка со
  // словом «неизвестно» пугает сильнее, чем её отсутствие.
  if (!status || !status.total) return null;

  const bad = status.down > 0;
  // Что именно легло, говорим прямо в строке: иначе за этим придётся
  // открывать лист, а плохую новость прячут в последнюю очередь.
  const trouble = bad
    ? status.down === 1
      ? t("status.oneDown", {
          country:
            (status.servers.find((one) => !one.up) || {}).country || t("status.node"),
        })
      : t("status.manyDown", { n: status.down })
    : "";

  return (
    <>
      <button
        type="button"
        className={"st-strip" + (bad ? " is-bad" : "")}
        onClick={() => {
          tmaHaptic("light");
          setOpen(true);
        }}
      >
        <span className="st-mark">{bad ? BAD_MARK : OK_MARK}</span>
        <span className="st-label">{t("status.title")}</span>
        {bad && <span className="st-trouble">{trouble}</span>}
        <span className="st-chev">{CHEV}</span>
      </button>

      {open && (
        <Sheet open title={t("status.title")} sub={t("status.lead")} onClose={() => setOpen(false)}>
          <div className="st-list">
            {status.servers.map((one) => (
              <div key={one.name} className="st-row">
                <Flag code={one.country_code} title={one.country || one.name} />
                <span className="st-row-name">{one.country || one.name}</span>
                <span className={"st-row-state" + (one.up ? "" : " is-bad")}>
                  {one.up ? t("status.up") : t("status.down")}
                </span>
              </div>
            ))}
          </div>
          {/* Тихая подпись: страница доступна и без входа — пригодится,
              когда в кабинет зайти не выходит. */}
          <p className="st-note">
            {t("status.cabinetNote")}{" "}
            <a href={`${BRAND.siteUrl}/status`} target="_blank" rel="noreferrer">
              {BRAND.domain}/status
            </a>
          </p>
        </Sheet>
      )}
    </>
  );
}
