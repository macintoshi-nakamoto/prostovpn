import { Link } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { useScrolled } from "../lib/hooks";
import "./site-header.css";

/**
 * Шапка лендинга.
 *
 * Над героем она прозрачная с белым логотипом; стоит прокрутить — становится
 * белой карточкой с тёмным логотипом, как в макете. Пункты меню ведут к
 * якорям секций. Кнопка справа зависит от того, вошёл ли посетитель: гостю —
 * «Подключить», вошедшему — «Кабинет».
 */
export function SiteHeader() {
  const scrolled = useScrolled(60);
  const { authed } = useSession();

  return (
    <header className={`sh${scrolled ? " sh-solid" : ""}`}>
      <div className="wrap sh-in">
        <a href="#top" className="sh-logo">
          <img src="/assets/logo.png" alt="PROSTO" />
        </a>
        <nav className="sh-nav">
          <a href="#speed">Скорость</a>
          <a href="#app">Приложение</a>
          <a href="#plans">Тарифы</a>
          <a href="#security">Безопасность</a>
          <Link to="/faq">FAQ</Link>
        </nav>
        <Link to={authed ? "/account" : "/login"} className="sh-cta">
          {authed ? "Кабинет" : "Войти"}
        </Link>
      </div>
    </header>
  );
}
