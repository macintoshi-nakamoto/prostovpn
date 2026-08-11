import { useEffect, useState } from "react";
import { api } from "../lib/api";
import "./setup-guide.css";

/**
 * Инструкция по установке для каждой платформы.
 *
 * Никакого «ключа подключения» из макета: у сервиса вход по логину и паролю,
 * поэтому шаги везде начинаются с «войдите теми же логином и паролем». Ссылка
 * на скачивание для Windows берётся живой из панели (/downloads), остальные
 * платформы пока ведут в сторы-заглушки.
 */
const SETUP = {
  windows: {
    title: "Установка на Windows",
    button: "Скачать для Windows",
    steps: [
      ["Скачайте установщик", "Поддерживаются Windows 10 и 11. Файл .msi ставится меньше чем за минуту."],
      ["Запустите файл", "Драйвер туннеля ставится автоматически, приложение появится в меню «Пуск»."],
      ["Войдите в аккаунт", "Введите тот же логин и пароль, что и здесь, в личном кабинете."],
      ["Нажмите кнопку подключения", "Сервер подберётся сам, при желании выберите страну вручную."],
    ],
  },
  ios: {
    title: "Установка на iPhone и iPad",
    button: "Открыть App Store",
    steps: [
      ["Скачайте приложение", "Найдите Prosto VPN в App Store на самом устройстве."],
      ["Войдите в аккаунт", "Логин и пароль те же, что и здесь, в личном кабинете."],
      ["Разрешите конфигурацию VPN", "iOS попросит подтвердить добавление профиля — нажмите «Разрешить»."],
      ["Нажмите кнопку подключения", "Сервер подберётся автоматически."],
    ],
  },
  android: {
    title: "Установка на Android",
    button: "Открыть Google Play",
    steps: [
      ["Скачайте приложение", "Prosto VPN есть в Google Play; для устройств без сервисов Google — APK на сайте."],
      ["Войдите в аккаунт", "Используйте логин и пароль от личного кабинета."],
      ["Подтвердите запрос системы", "Android покажет запрос на создание VPN-подключения — нажмите «ОК»."],
      ["Включите автозапуск", "В настройках приложения включите подключение при старте системы."],
    ],
  },
  macos: {
    title: "Установка на macOS",
    button: "Скачать для macOS",
    steps: [
      ["Скачайте установщик", "Файл .dmg подходит для Apple Silicon и Intel."],
      ["Перенесите в «Программы»", "Откройте образ и перетащите Prosto VPN в папку Applications."],
      ["Войдите и разрешите профиль", "При первом запуске macOS попросит пароль администратора."],
      ["Закрепите в строке меню", "Иконка в меню-баре подключает одним кликом."],
    ],
  },
};

const ORDER = [
  ["windows", "Windows"],
  ["ios", "iOS"],
  ["android", "Android"],
  ["macos", "macOS"],
];

export function SetupGuide({ login }) {
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

  const cfg = SETUP[os];
  const href = downloads[os];

  return (
    <div className="sg">
      <div className="sg-note">
        <span className="sg-note-l">Вход в приложении</span>
        <p>
          На всех платформах вход одинаковый: логин <b>{login}</b> и пароль от этого кабинета.
          Никаких ключей и файлов настройки — страны приложение получает из аккаунта само.
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
          <h2>{cfg.title}</h2>
          {href ? (
            <a className="btn btn-dark sg-dl" href={href} download>
              {cfg.button}
            </a>
          ) : (
            <span className="sg-soon">Скоро</span>
          )}
        </div>
        <div className="sg-steps">
          {cfg.steps.map(([title, text], i) => (
            <div className="sg-step" key={i}>
              <span className="sg-num">{i + 1}</span>
              <span className="sg-step-body">
                <span className="sg-step-title">{title}</span>
                <span className="sg-step-text">{text}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="sg-help">
          <span>Что-то не подключается? Поддержка в Telegram отвечает быстро.</span>
          <a href="https://t.me/prosto_vpn_supp" target="_blank" rel="noreferrer">
            @prosto_vpn_supp
          </a>
        </div>
      </div>
    </div>
  );
}
