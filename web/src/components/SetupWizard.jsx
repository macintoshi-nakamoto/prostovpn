import { useEffect, useMemo, useState } from "react";
import { QrCode } from "./QrCode.jsx";
import { api } from "../lib/api";
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
  { id: "ios", icon: "phone", ours: false },
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

export function SetupWizard({ icons, login, onExternal, onDone }) {
  const { t } = useI18n();

  const guessed = useMemo(guessDevice, []);
  // null — ещё не ответили; строка — выбранное устройство.
  const [device, setDevice] = useState(null);
  // Ставим сюда же или на другое: от этого зависит, кнопка или код.
  const [sameDevice, setSameDevice] = useState(true);
  const [picking, setPicking] = useState(!guessed);
  const [downloads, setDownloads] = useState(null);

  useEffect(() => {
    let alive = true;
    api
      .downloads()
      .then((list) => alive && setDownloads(Array.isArray(list) ? list : []))
      .catch(() => alive && setDownloads([]));
    return () => {
      alive = false;
    };
  }, []);

  const answerHere = () => {
    setDevice(guessed);
    setSameDevice(true);
  };

  const pick = (id) => {
    setDevice(id);
    setSameDevice(id === guessed);
    setPicking(false);
  };

  const back = () => {
    setDevice(null);
    setPicking(!guessed);
  };

  // ── шаг 1: куда ставим ────────────────────────────────────────────────
  if (!device) {
    return (
      <div className="wz">
        <div className="wz-hi">
          <span className="wz-hi-t">{t("wizard.hiTitle")}</span>
          <span className="wz-hi-s">{t("wizard.hiLead")}</span>
        </div>

        {!picking && guessed ? (
          <div className="wz-card">
            <span className="wz-ic">{icons[DEVICES.find((d) => d.id === guessed).icon]}</span>
            <span className="wz-q">{t(`wizard.here.${guessed}`)}</span>
            <button type="button" className="wz-btn wz-btn-on" onClick={answerHere}>
              {t("wizard.yesHere")}
            </button>
            <button type="button" className="wz-btn" onClick={() => setPicking(true)}>
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
  const pageUrl =
    typeof window !== "undefined" ? window.location.origin + "/account/guide" : "";

  return (
    <div className="wz">
      <button type="button" className="wz-back" onClick={back}>
        {t("wizard.back")}
      </button>

      <div className="wz-hi">
        <span className="wz-ic wz-ic-lg">{icons[meta.icon]}</span>
        <span className="wz-hi-t">{t(`wizard.plan.${device}.title`)}</span>
        <span className="wz-hi-s">{t(`wizard.plan.${device}.lead`)}</span>
      </div>

      {!sameDevice && (
        <div className="wz-step">
          <span className="wz-num">1</span>
          <div className="wz-step-body">
            <span className="wz-step-t">{t("wizard.otherTitle")}</span>
            <span className="wz-step-s">{t("wizard.otherLead")}</span>
            <div className="wz-qr">
              <QrCode value={pageUrl} />
            </div>
          </div>
        </div>
      )}

      {meta.ours ? (
        <>
          <div className="wz-step">
            <span className="wz-num">{sameDevice ? 1 : 2}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.getApp")}</span>
              <span className="wz-step-s">{t(`wizard.plan.${device}.get`)}</span>
              {sameDevice && file?.url && (
                <a className="wz-cta" href={file.url}>
                  {t(`wizard.plan.${device}.button`)}
                </a>
              )}
            </div>
          </div>

          <div className="wz-step">
            <span className="wz-num">{sameDevice ? 2 : 3}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.signIn")}</span>
              <span className="wz-step-s">{t("wizard.signInLead")}</span>
              {login && (
                <span className="wz-login">
                  {t("wizard.yourLogin")} <b>{login}</b>
                </span>
              )}
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="wz-step">
            <span className="wz-num">{sameDevice ? 1 : 2}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.iosGet")}</span>
              <span className="wz-step-s">{t("wizard.iosGetLead")}</span>
              <a
                className="wz-cta"
                href="https://apps.apple.com/app/amneziavpn/id1600529900"
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("wizard.iosStore")}
              </a>
            </div>
          </div>

          <div className="wz-step">
            <span className="wz-num">{sameDevice ? 2 : 3}</span>
            <div className="wz-step-body">
              <span className="wz-step-t">{t("wizard.iosKey")}</span>
              <span className="wz-step-s">{t("wizard.iosKeyLead")}</span>
              <button type="button" className="wz-cta" onClick={onDone}>
                {t("wizard.iosKeyBtn")}
              </button>
            </div>
          </div>
        </>
      )}

      <div className="wz-done">
        <span className="wz-done-t">{t("wizard.doneTitle")}</span>
        <span className="wz-done-s">{t("wizard.doneLead")}</span>
      </div>

      <button type="button" className="wz-quiet" onClick={onExternal}>
        {t("wizard.haveApp")}
      </button>
    </div>
  );
}
