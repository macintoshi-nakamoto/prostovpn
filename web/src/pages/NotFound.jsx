import { Link } from "react-router-dom";
import "./not-found.css";

export function NotFound() {
  return (
    <div className="nf">
      <img className="nf-logo" src="/assets/logo.png" alt="PROSTO" />
      <div className="nf-code">404</div>
      <h1>Такой страницы нет</h1>
      <p>Возможно, в адресе опечатка — или страница переехала.</p>
      <div className="nf-actions">
        <Link to="/" className="btn btn-primary">
          На главную
        </Link>
        <Link to="/account" className="btn btn-outline">
          В личный кабинет
        </Link>
      </div>
    </div>
  );
}
