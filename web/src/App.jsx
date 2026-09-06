import { useEffect, useLayoutEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { tmaSignedOut, useSession } from "./lib/session.jsx";
import { initTma, isTma, tmaStartParam } from "./lib/telegram.js";
import { rememberRef } from "./lib/referral.js";
import { BRAND } from "./lib/brand.js";
import { useTheme } from "./lib/theme.jsx";
import { Landing } from "./pages/Landing.jsx";
import { Login } from "./pages/Login.jsx";
import { Reset } from "./pages/Reset.jsx";
import { Account } from "./pages/Account.jsx";
import { Guide } from "./pages/Guide.jsx";
import { Legal } from "./pages/Legal.jsx";
import { LegalDoc } from "./pages/LegalDoc.jsx";
import { NotFound } from "./pages/NotFound.jsx";
import { Status } from "./pages/Status.jsx";
import { Blocks } from "./pages/Blocks.jsx";
import { Faq } from "./pages/Faq.jsx";

// Формат приложения: класс app на корне — в Telegram всегда, на сайте на
// маршрутах кабинета. useLayoutEffect — до отрисовки, чтобы вид не мигал.
// Первичную установку до рендера делает скрипт в index.html, но снять
// класс (например, редирект /account -> /login без токена) может только он.
//
// Здесь же тема: она идёт за той же границей — кабинет тёмный, витрина
// светлая (см. lib/theme.jsx). Считать «где мы» дважды в разных местах
// незачем, а разойдись эти два расчёта — вид и цвет спорили бы друг с другом.
function AppFormat() {
  const { pathname } = useLocation();
  const { follow } = useTheme();
  useLayoutEffect(() => {
    const app = isTma() || pathname === "/account" || pathname.startsWith("/account/");
    document.documentElement.classList.toggle("app", app);
    // У бренда без витрины светлой половины нет вовсе: там кабинет — всё.
    follow(app || !BRAND.landing);
  }, [pathname, follow]);
  return null;
}

function CatchReferral() {
  useEffect(() => {
    rememberRef();
  }, []);
  return null;
}

function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }

    window.scrollTo(0, 0);
    const frame = requestAnimationFrame(() => window.scrollTo(0, 0));
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (window.location.hash) return;
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}

// Мини-приложение Telegram: развернуться на весь экран и войти самим по
// подписи initData, пока человек смотрит на пустой фон. Не вышло (Telegram
// не привязан к учётке) — покажем обычную форму входа.
function TmaGate({ children }) {
  const { authed, signInTelegram } = useSession();
  const [pending, setPending] = useState(() => isTma() && !authed && !tmaSignedOut());

  useEffect(() => {
    initTma();
    // Реферальный код из ссылки запуска — в ту же память, что и ?ref= на
    // сайте: регистрация подхватит его сама.
    const param = tmaStartParam();
    if (param) rememberRef("?ref=" + encodeURIComponent(param));
  }, []);

  useEffect(() => {
    if (!pending) return;
    let alive = true;
    (async () => {
      try {
        await signInTelegram();
      } catch {
        // не привязан или подпись устарела — дальше обычный вход
      }
      if (alive) setPending(false);
    })();
    return () => {
      alive = false;
    };
  }, [pending, signInTelegram]);

  if (pending) return <div className="tma-boot" aria-hidden="true" />;
  return children;
}

function Private({ children }) {
  const { authed } = useSession();
  const location = useLocation();
  if (!authed) return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

export function App() {
  return (
    <>
      <AppFormat />
      <CatchReferral />
      <ScrollToTop />
      <TmaGate>
      <Routes>
        {/* Бренд без лендинга (Rus VPN): корень — сразу кабинет, как в Telegram. */}
        <Route
          path="/"
          element={isTma() || !BRAND.landing ? <Navigate to="/account" replace /> : <Landing />}
        />
        <Route path="/login" element={<Login />} />
        <Route path="/reset" element={<Reset />} />
        <Route
          path="/account"
          element={
            <Private>
              <Account />
            </Private>
          }
        />
        <Route
          path="/account/:section"
          element={
            <Private>
              <Account />
            </Private>
          }
        />
        <Route path="/guide" element={<Guide />} />
        {/* Публичная: человеку, у которого не подключается, вход не нужен. */}
        <Route path="/status" element={<Status />} />
        <Route path="/blocks" element={<Blocks />} />
        <Route path="/terms" element={<LegalDoc doc="terms" />} />
        <Route path="/privacy" element={<LegalDoc doc="privacy" />} />
        <Route path="/aup" element={<LegalDoc doc="aup" />} />
        <Route path="/refund" element={<LegalDoc doc="refund" />} />
        <Route path="/licenses" element={<LegalDoc doc="licenses" />} />
        <Route path="/faq" element={<Faq />} />
        <Route path="/contacts" element={<Legal doc="contacts" />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      </TmaGate>
    </>
  );
}
