import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { QrCode } from "./QrCode.jsx";
import { api } from "../lib/api";
import { isTma, pushBack, tmaHaptic, tmaOpenLink } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Мастер установки: ведёт человека за руку от «что вообще делать» до
 * работающего VPN.
 *
 * Правила, по которым он собран:
 *   * один вопрос на экран — выбирать из пяти вариантов сразу тяжело;
 *   * спрашиваем не «что у вас за устройство», а «куда ставим»: кабинет
 *     часто открыт на компьютере, а настроить хотят телефон, и определение
 *     по браузеру тут только подсказка;
 *   * если ставим не на это устройство — вместо кнопки «скачать» показываем
 *     код для камеры: скачивать на компьютер то, что нужно на телефоне,
 *     бессмысленно;
 *   * ни слова из нашего словаря: ни протоколов, ни узлов, ни подписок.
 */

/** Что мы умеем и как это выглядит для человека. */
const DEVICES = [
  { id: "windows", icon: "windows", ours: true },
  { id: "android", icon: "android", ours: true },
  { id: "macos", icon: "laptop", ours: true },
  { id: "ios", icon: "apple", ours: false },
  { id: "tv", icon: "tv", ours: true },
];

/** Что из этого — то же самое, что открыто прямо сейчас. */
function guessDevice() {
  if (typeof navigator === "undefined") return null;
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  if (/Android/i.test(ua)) return "android";
  if (/Macintosh|Mac OS X/i.test(ua)) return "macos";
  if (/Windows/i.test(ua)) return "windows";
  return null;
}

const DOWNLOAD_KEY = { windows: "windows", android: "android", tv: "android", macos: "macos" };

/* Значки для строк входа. Держим здесь, а не в общем наборе кабинета:
   больше нигде глаз и листы не нужны. */
const EYE = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
    <circle cx="12" cy="12" r="2.7" />
  </svg>
);
const EYE_OFF = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4l16 16" />
    <path d="M9.6 5.7A11 11 0 0 1 12 5.5c6.4 0 10 6.5 10 6.5a18 18 0 0 1-3.5 4.2" />
    <path d="M6.4 7.7A18 18 0 0 0 2 12s3.6 6.5 10 6.5c1 0 1.9-.1 2.7-.4" />
    <path d="M9.9 9.9a2.7 2.7 0 0 0 3.8 3.8" />
  </svg>
);
const COPY = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="9" y="9" width="11" height="11" rx="2.5" />
    <path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-7A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15" />
  </svg>
);
const CHECK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4.5 12.5l5 5 10-11" />
  </svg>
);

/**
 * Телевизор — исключение из правила «не показываем скачивание чужому
 * устройству». Кабинет на телевизоре никто не открывает, определить его
 * по браузеру нельзя, а инструкция прямо говорит: скачайте файл на телефон
 * и передайте. Без кнопки шаг некуда выполнять.
 */
const TV = "tv";

export function SetupWizard({ icons, login, onExternal, onDone }) {
  const { t } = useI18n();

  const guessed = useMemo(guessDevice, []);
  const inTelegram = useMemo(isTma, []);
  // null — ещё не ответили; строка — выбранное устройство.
  const [device, setDevice] = useState(null);
  // Ставим сюда же или на другое: от этого зависит, кнопка или код.
  const [sameDevice, setSameDevice] = useState(true);
  const [picking, setPicking] = useState(!guessed);
  const [downloads, setDownloads] = useState(null);
  // «Назад» должен вернуть туда, откуда ушли: с сетки — на сетку, с
  // вопроса «ставим сюда?» — на вопрос. Иначе смена устройства стоит
  // двух лишних нажатий каждый раз.
  const [fromGrid, setFromGrid] = useState(false);
  // Что именно скопировали: логин или пароль.
  const [copied, setCopied] = useState("");
  // Логин с паролем человеку выдали при регистрации, и в мини-приложении
  // он их ни разу не видел — а в приложении на компьютере спрашивают
  // именно их. Пароль приходит, только пока он выданный нами.
  const [creds, setCreds] = useState(null);
  // Пароль под точками, пока не попросили показать: экран установки
  // открывают при людях, а подглядеть его хватает одного взгляда.
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .downloads()
      .then((list) => alive && setDownloads(Array.isArray(list) ? list : []))
      .catch(() => alive && setDownloads([]));
    api
      .credentials()
      .then((res) => alive && setCreds(res))
      .catch(() => alive && setCreds({}));
    return () => {
      alive = false;
    };
  }, []);

  const answerHere = () => {
    setDevice(guessed);
    setSameDevice(true);
    setFromGrid(false);
  };

  const pick = (id) => {
    setDevice(id);
    setSameDevice(id === guessed);
    setFromGrid(true);
    setPicking(false);
  };

  // Один шаг назад, какой бы экран ни был открыт. Дальше первого экрана
  // не отступаем: там мастер кончается, а из вкладки уводит таб-бар.
  const back = () => {
    if (device) {
      setDevice(null);
      setPicking(fromGrid || !guessed);
      return;
    }
    if (picking && guessed) setPicking(false);
  };

  // Системная кнопка «назад» Telegram и кнопка браузера — через общий стек
  // приложения (pushBack). Обработчик наружу отдаём стабильный: back
  // пересоздаётся каждый рендер, а перезапуск эффекта дёргал бы историю
  // на каждом из них — та же оговорка, что в ScreenShell.
  const backRef = useRef(back);
  useEffect(() => {
    backRef.current = back;
  });
  const stableBack = useCallback(() => backRef.current(), []);

  // Одна запись на весь мастер, а не по одной на экран: стек сам
  // возвращает её на место на каждом нажатии (bindWebBack, backDispatch),
  // поэтому её хватает на сколько угодно шагов. Перерегистрация на каждом
  // экране устраивала гонку pop и push в истории.
  const needsBack = Boolean(device) || (picking && Boolean(guessed));
  useEffect(() => {
    if (!needsBack) return undefined;
    return pushBack(stableBack);
  }, [needsBack, stableBack]);

  // Данные надо перенести в другое приложение, а выделить текст в вебвью
  // Telegram почти невозможно — поэтому строки нажимаются.
  const copy = async (value, key) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      tmaHaptic("light");
      setCopied(key);
      setTimeout(() => setCopied((cur) => (cur === key ? "" : cur)), 1400);
    } catch {}
  };

  // ── шаг 1: куда ставим ────────────────────────────────────────────────
  if (!device) {
    return (
      <div className="wz wz-first">
        <div className="wz-hi">
          <span className="wz-hi-t">{t("wizard.hiTitle")}</span>
          <span className="wz-hi-s">{t("wizard.hiLead")}</span>
        </div>

        {!picking && guessed ? (
          <div className="wz-card">
            <span className="wz-ic">{icons[DEVICES.find((d) => d.id === guessed).icon]}</span>
            <span className="wz-q">{t(`wizard.here.${guessed}`)}</span>
            <button type="button" className="ap-cta wz-go" onClick={answerHere}>
              {t("wizard.yesHere")}
            </button>
            <button
              type="button"
              className="ap-cta wz-go wz-go-alt"
              onClick={() => setPicking(true)}
            >
              {t("wizard.noOther")}
            </button>
          </div>
        ) : (
          <>
            <span className="wz-h">{t("wizard.pickTitle")}</span>
            <div className="wz-grid">
              {DEVICES.map((one) => (
                <button
                  key={one.id}
                  type="button"
                  className="wz-tile"
                  onClick={() => pick(one.id)}
                >
                  <span className="wz-tile-ic">{icons[one.icon]}</span>
                  <span className="wz-tile-t">{t(`wizard.device.${one.id}`)}</span>
                </button>
              ))}
            </div>
          </>
        )}

        <button type="button" className="wz-quiet" onClick={onExternal}>
          {t("wizard.haveApp")}
        </button>
      </div>
    );
  }

  // ── шаг 2: что делать с выбранным устройством ─────────────────────────
  const meta = DEVICES.find((one) => one.id === device);
  const file = (downloads || []).find((row) => row.platform === DOWNLOAD_KEY[device]);
  // Именно /guide, а не /account/guide: код наводят на устройство, где
  // сессии заведомо нет, а кабинет за паролем — там открылась бы форма
  // входа вместо инструкции. /guide открыт всем.
  const pageUrl = typeof window !== "undefined" ? window.location.origin + "/guide" : "";
  // У телевизора нет камеры — предлагать навести её на код бессмысленно.
  const showQr = !sameDevice && device !== TV;
  const firstStep = showQr ? 2 : 1;

  return (
    <div className="wz">
      {/* В Telegram назад ведёт системная стрелка в шапке — своя рядом с
          ней была бы второй кнопкой об одном и том же. На сайте она нужна:
          там кроме кнопки браузера ткнуть некуда. */}
      {!inTelegram && (
        <button type="button" className="wz-back" onClick={back}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" />
          </svg>
          {t("wizard.back")}
        </button>
      )}

      <div className="wz-hi">
        <span className="wz-ic wz-ic-lg">{icons[meta.icon]}</span>
        <span className="wz-hi-t">{t(`wizard.plan.${device}.title`)}</span>
        <span className="wz-hi-s">{t(`wizard.plan.${device}.lead`)}</span>
      </div>

      {showQr && (
        <div className="wz-step">
          <span className="wz-num">1</span>
          <div className="wz-step-body">
            <span className="wz-step-t">{t("wizard.otherTitle")}</span>
            <span className="wz-step-s">{t("wizard.otherLead")}</span>
            {/* Код по центру колонки, под ним — ссылка текстом: камера
                есть не у всякого, а на телевизоре её нет вовсе. */}
            <div className="wz-qr-box">
              <div className="wz-qr">
                <QrCode value={pageUrl} />
              </div>
              <button
                type="button"
                className="tps-alt wz-qr-copy"
                onClick={() => copy(pageUrl, "link")}
              >
                {copied === "link" ? t("wizard.copied") : t("wizard.copyLink")}
              </button>
            </div>
          </div>
        </div>
      )}

      {meta.ours ? (
        <>
          <div className="wz-step">
            <span className="wz-num">{firstStep}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.getApp")}</span>
              <span className="wz-step-s">{t(`wizard.plan.${device}.get`)}</span>
              {(sameDevice || device === TV) &&
                (downloads === null ? (
                  <span className="wz-wait">{t("wizard.waitFile")}</span>
                ) : file?.url ? (
                  // Не ссылка: в вебвью Telegram файл открылся бы просмотром
                  // вместо скачивания. tmaOpenLink уводит во внешний браузер.
                  <button
                    type="button"
                    className="ap-cta st-g-cta"
                    onClick={() => {
                      tmaHaptic("light");
                      tmaOpenLink(file.url);
                    }}
                  >
                    {t(`wizard.plan.${device}.button`)}
                  </button>
                ) : (
                  <a className="wz-fallback" href="/guide" target="_blank" rel="noreferrer noopener">
                    {t("wizard.openGuide")}
                  </a>
                ))}
            </div>
          </div>

          <div className="wz-step">
            <span className="wz-num">{firstStep + 1}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.signIn")}</span>
              <span className="wz-step-s">{t("wizard.signInLead")}</span>
              {/* Логин и пароль рядом: именно их спрашивает приложение, и
                  именно их человек из Telegram никогда не видел. Пароля
                  нет, если он задал свой — тогда показать его нам нечем. */}
              <div className="wz-creds">
                <div className="wz-cred">
                  <span className="wz-cred-k">{t("account.webLoginLogin")}</span>
                  <span className="wz-cred-v">{creds?.login || login}</span>
                  <button
                    type="button"
                    className="wz-cred-b"
                    aria-label={t("wizard.copyAria")}
                    onClick={() => copy(creds?.login || login, "login")}
                  >
                    {copied === "login" ? CHECK : COPY}
                  </button>
                </div>
                {creds?.password ? (
                  <div className="wz-cred">
                    <span className="wz-cred-k">{t("account.webLoginPassword")}</span>
                    {/* Точек ровно столько, сколько символов: длина не
                        секрет, зато строка не прыгает при раскрытии. */}
                    <span className="wz-cred-v">
                      {shown ? creds.password : "•".repeat(creds.password.length)}
                    </span>
                    <button
                      type="button"
                      className="wz-cred-b"
                      aria-label={shown ? t("wizard.hidePwd") : t("wizard.showPwd")}
                      onClick={() => setShown((on) => !on)}
                    >
                      {shown ? EYE_OFF : EYE}
                    </button>
                    <button
                      type="button"
                      className="wz-cred-b"
                      aria-label={t("wizard.copyAria")}
                      onClick={() => copy(creds.password, "password")}
                    >
                      {copied === "password" ? CHECK : COPY}
                    </button>
                  </div>
                ) : creds?.is_generated === false ? (
                  // Именно этот флаг, а не «пароля в ответе нет»: при сбое
                  // сети мы бы иначе уверяли, что человек задал пароль сам.
                  <span className="wz-cred-note">{t("wizard.ownPassword")}</span>
                ) : null}
              </div>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="wz-step">
            <span className="wz-num">{firstStep}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.iosGet")}</span>
              <span className="wz-step-s">{t("wizard.iosGetLead")}</span>
              <a
                className="ap-cta st-g-cta"
                href="https://apps.apple.com/app/amneziavpn/id1600529900"
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("wizard.iosStore")}
              </a>
            </div>
          </div>

          <div className="wz-step">
            <span className="wz-num">{firstStep + 1}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.iosKey")}</span>
              <span className="wz-step-s">{t("wizard.iosKeyLead")}</span>
              <button type="button" className="ap-cta st-g-cta" onClick={onDone}>
                {t("wizard.iosKeyBtn")}
              </button>
            </div>
          </div>
        </>
      )}

      <div className="wz-done">
        <span className="wz-done-t">{t("wizard.doneTitle")}</span>
        <span className="wz-done-s">{t("wizard.doneLead")}</span>
        {/* Без этой кнопки из мастера некуда деться: onDone зовёт только
            ветка iPhone, а остальные оставались в нём навсегда — и раздел
            установки с логином, гайдами и ключами был недостижим. */}
        {meta.ours && (
          <button type="button" className="ap-cta st-g-cta" onClick={onDone}>
            {t("wizard.doneBtn")}
          </button>
        )}
      </div>

      <button type="button" className="wz-quiet" onClick={onExternal}>
        {t("wizard.haveApp")}
      </button>
    </div>
  );
}
