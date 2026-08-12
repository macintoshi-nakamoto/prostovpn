import { Link } from "react-router-dom";
import { useT } from "../lib/i18n/index.jsx";
import "./not-found.css";

export function NotFound() {
  const t = useT();
  return (
    <div className="nf">
      <img className="nf-logo" src="/assets/logo.png" alt="PROSTO" />
      <div className="nf-code">404</div>
      <h1>{t("notFound.title")}</h1>
      <p>{t("notFound.text")}</p>
      <div className="nf-actions">
        <Link to="/" className="btn btn-primary">
          {t("notFound.home")}
        </Link>
        <Link to="/account" className="btn btn-outline">
          {t("notFound.account")}
        </Link>
      </div>
    </div>
  );
}
