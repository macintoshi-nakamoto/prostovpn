import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./lib/session.jsx";
import { rememberRef } from "./lib/referral.js";
import { Landing } from "./pages/Landing.jsx";
import { Login } from "./pages/Login.jsx";
import { Reset } from "./pages/Reset.jsx";
import { Account } from "./pages/Account.jsx";
import { Guide } from "./pages/Guide.jsx";
import { Legal } from "./pages/Legal.jsx";
import { LegalDoc } from "./pages/LegalDoc.jsx";
import { NotFound } from "./pages/NotFound.jsx";

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

function Private({ children }) {
  const { authed } = useSession();
  const location = useLocation();
  if (!authed) return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

export function App() {
  return (
    <>
      <CatchReferral />
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
        <Route
          path="/account/:section"
          element={
            <Private>
              <Account />
            </Private>
          }
        />
        <Route path="/guide" element={<Guide />} />
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
