import { Link, useLocation } from "react-router-dom";
import { Picture } from "./Picture.jsx";
import { Controls } from "./Controls.jsx";
import { useSession } from "../lib/session.jsx";
import { useScrolled } from "../lib/hooks";
import { useT } from "../lib/i18n/index.jsx";
import "./site-header.css";

/**
 * Шапка лендинга.
 *
 * Над героем она прозрачная с белым логотипом; стоит прокрутить — становится
 * белой карточкой с тёмным логотипом, как в макете. Пункты меню ведут к
 * якорям секций. Кнопка справа зависит от того, вошёл ли посетитель: гостю —
 * «Подключить», вошедшему — «Кабинет».
 *
 * На странице входа кнопки нет вовсе: звать войти того, кто уже стоит перед
 * формой входа, незачем, а вторая оранжевая кнопка рядом с главной отняла бы
 * у неё половину внимания.
 */
export function SiteHeader() {
  const scrolled = useScrolled(60);
  const { authed } = useSession();
  const { pathname } = useLocation();
  const t = useT();
  const onLanding = pathname === "/";
  const onLogin = pathname === "/login";

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
          <Picture src="/assets/logo.png" alt="PROSTO" />
        </Link>
        <nav className="sh-nav">
          <a href={section("speed")}>{t("nav.speed")}</a>
          <a href={section("app")}>{t("nav.app")}</a>
          <a href={section("plans")}>{t("nav.plans")}</a>
          <a href={section("security")}>{t("nav.security")}</a>
          <Link to="/guide">{t("nav.guide")}</Link>
          <Link to="/faq">{t("nav.faq")}</Link>
        </nav>
        {/* Переключатели и кнопка входа — одной группой: на узком экране меню
            пропадает, и без обёртки space-between растащил бы их по краям. */}
        <div className="sh-right">
          <Controls />
          {!onLogin && (
            <Link to={authed ? "/account" : "/login"} className="sh-cta">
              {authed ? t("nav.account") : t("nav.signin")}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
