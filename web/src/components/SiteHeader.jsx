import { Link, useLocation } from "react-router-dom";
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
  const { pathname } = useLocation();
  const onLanding = pathname === "/";

  /*
  Логотип всегда ведёт на главную. Раньше это была ссылка на якорь #top: на
  самой главной она прокручивала наверх, а на внутренних страницах лишь
  дописывала /privacy#top и никуда не уводила. Теперь на главной она
  прокручивает, а с любой другой страницы — переходит на главную.
  */
  const toTop = (e) => {
    if (!onLanding) return;
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Якоря секций работают только на главной; с остальных страниц ведём
  // на главную с якорем, иначе ссылка молча остаётся на месте.
  const section = (id) => (onLanding ? `#${id}` : `/#${id}`);

  return (
    <header className={`sh${scrolled ? " sh-solid" : ""}`}>
      <div className="wrap sh-in">
        <Link to="/" className="sh-logo" onClick={toTop}>
          <img src="/assets/logo.png" alt="PROSTO" />
        </Link>
        <nav className="sh-nav">
          <a href={section("speed")}>Скорость</a>
          <a href={section("app")}>Приложение</a>
          <a href={section("plans")}>Тарифы</a>
          <a href={section("security")}>Безопасность</a>
          <Link to="/faq">FAQ</Link>
        </nav>
        <Link to={authed ? "/account" : "/login"} className="sh-cta">
          {authed ? "Кабинет" : "Войти"}
        </Link>
      </div>
    </header>
  );
}
