import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./lib/session.jsx";
import { Landing } from "./pages/Landing.jsx";
import { Login } from "./pages/Login.jsx";
import { Account } from "./pages/Account.jsx";
import { Legal } from "./pages/Legal.jsx";
import { NotFound } from "./pages/NotFound.jsx";

/** Каждый переход — наверх страницы: иначе кабинет открывается прокрученным. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
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
        <Route
          path="/account"
          element={
            <Private>
              <Account />
            </Private>
          }
        />
        <Route path="/terms" element={<Legal doc="terms" />} />
        <Route path="/privacy" element={<Legal doc="privacy" />} />
        <Route path="/faq" element={<Legal doc="faq" />} />
        <Route path="/contacts" element={<Legal doc="contacts" />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}
