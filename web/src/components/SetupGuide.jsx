import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n/index.jsx";
import { SUPPORT_EMAIL, SUPPORT_MAILTO, SUPPORT_TELEGRAM, SUPPORT_TELEGRAM_NAME } from "../lib/contacts.js";
import "./setup-guide.css";

/**
 * Инструкция по установке для каждой платформы.
 *
 * Никакого «ключа подключения» из макета: у сервиса вход по логину и паролю,
 * поэтому шаги везде начинаются с «войдите теми же логином и паролем». Ссылка
 * на скачивание для Windows берётся живой из панели (/downloads), остальные
 * платформы пока ведут в сторы-заглушки.
 *
 * Порядок платформ и их названия — здесь: «Windows» и «macOS» не переводятся,
 * а порядок задаёт вид вкладок. Шаги и заголовки — в словаре.
 */
const ORDER = [
  ["windows", "Windows"],
  ["ios", "iOS"],
  ["android", "Android"],
  ["macos", "macOS"],
];

export function SetupGuide({ login }) {
  const { t, raw } = useI18n();
  const [os, setOs] = useState("windows");
  const [downloads, setDownloads] = useState({});

  useEffect(() => {
    api
      .downloads()
      .then((list) => {
        if (!Array.isArray(list)) return;
        const map = {};
        for (const r of list) map[r.platform] = r.url;
        setDownloads(map);
      })
      .catch(() => {});
  }, []);

  const href = downloads[os];
  const steps = raw(`setup.${os}.steps`);

  return (
    <div className="sg">
      <div className="sg-note">
        <span className="sg-note-l">{t("setup.noteLabel")}</span>
        {/*
        Логин — жирным внутри фразы, поэтому строка собирается из двух половин
        по «{login}», а не подставляется целиком: подстановка вернула бы текст,
        и выделить в нём одно слово было бы нечем.
        */}
        <p>
          {t("setup.note").split("{login}")[0]}
          <b>{login}</b>
          {t("setup.note").split("{login}")[1]}
        </p>
      </div>

      <div className="sg-os">
        {ORDER.map(([id, label]) => (
          <button key={id} className={os === id ? "active" : ""} onClick={() => setOs(id)}>
            {label}
          </button>
        ))}
      </div>

      <div className="sg-card">
        <div className="sg-card-head">
          <h2>{t(`setup.${os}.title`)}</h2>
          {href ? (
            <a className="btn btn-dark sg-dl" href={href} download>
              {t(`setup.${os}.button`)}
            </a>
          ) : (
            <span className="sg-soon">{t("setup.soon")}</span>
          )}
        </div>
        <div className="sg-steps">
          {steps.map(([title, text], i) => (
            <div className="sg-step" key={i}>
              <span className="sg-num">{i + 1}</span>
              <span className="sg-step-body">
                <span className="sg-step-title">{title}</span>
                <span className="sg-step-text">{text}</span>
              </span>
            </div>
          ))}
        </div>
        {/* Развёрнутая инструкция — со скриншотами и разделом про раздельное
            туннелирование: здесь только пять шагов, а вопросы обычно про то,
            чего в них нет. */}
        <div className="sg-help">
          <Link to="/guide">{t("setup.moreGuide")}</Link>
        </div>
        <div className="sg-help">
          <span>{t("setup.helpText")}</span>
          <a href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
            {SUPPORT_TELEGRAM_NAME}
          </a>
          <a href={SUPPORT_MAILTO}>{SUPPORT_EMAIL}</a>
        </div>
      </div>
    </div>
  );
}
