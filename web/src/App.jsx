import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./lib/session.jsx";
import { Landing } from "./pages/Landing.jsx";
import { Login } from "./pages/Login.jsx";
import { Reset } from "./pages/Reset.jsx";
import { Account } from "./pages/Account.jsx";
import { Guide } from "./pages/Guide.jsx";
import { Legal } from "./pages/Legal.jsx";
import { LegalDoc } from "./pages/LegalDoc.jsx";
import { NotFound } from "./pages/NotFound.jsx";

/**
 * Страница всегда открывается сверху.
 *
 * Две разные вещи. Переход по маршруту — прокрутка в ноль, иначе кабинет
 * открывается с середины. Перезагрузка — браузер сам возвращает прежнее
 * положение, и человек видит середину лендинга вместо начала; отключаем это
 * через scrollRestoration и прокручиваем сами, уже после того как React
 * отрисовал первый кадр.
 */
function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
    // Первый кадр может прийти раньше, чем браузер применит своё
    // восстановление, поэтому дублируем прокрутку следующим кадром.
    window.scrollTo(0, 0);
    const frame = requestAnimationFrame(() => window.scrollTo(0, 0));
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    // Якорь в адресе — намеренный переход к секции, его не перебиваем.
    if (window.location.hash) return;
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}

/** Кабинет — только для вошедших; остальных отправляем на вход. */
function Private({ children }) {
  const { authed } = useSession();
  const location = useLocation();
  if (!authed) return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

export function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />
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
        <Route path="/guide" element={<Guide />} />
        {/* Юридические документы — своими страницами: у каждого свой адрес,
            на который он же и ссылается изнутри. */}
        <Route path="/terms" element={<LegalDoc doc="terms" />} />
        <Route path="/privacy" element={<LegalDoc doc="privacy" />} />
        <Route path="/aup" element={<LegalDoc doc="aup" />} />
        <Route path="/refund" element={<LegalDoc doc="refund" />} />
        <Route path="/licenses" element={<LegalDoc doc="licenses" />} />
        <Route path="/faq" element={<Legal doc="faq" />} />
        <Route path="/contacts" element={<Legal doc="contacts" />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}
