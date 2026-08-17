import { Link } from "react-router-dom";
import { Picture } from "./Picture.jsx";
import { useT } from "../lib/i18n/index.jsx";
import {
  NEWS_TELEGRAM,
  SUPPORT_EMAIL,
  SUPPORT_MAILTO,
  SUPPORT_TELEGRAM,
  SUPPORT_TELEGRAM_NAME,
} from "../lib/contacts.js";
import "./site-footer.css";

/** Подвал лендинга: навигация, контакт поддержки, копирайт. Из макета. */
export function SiteFooter() {
  const t = useT();

  return (
    <footer className="sf">
      <div className="wrap sf-in">
        <Picture className="sf-logo" src="/assets/logo.png" alt="PROSTO" />

        <div className="sf-cols">
          <div>
            <a href="#plans">{t("footer.plans")}</a>
            <a href="#app">{t("footer.app")}</a>
            <a href="#speed">{t("footer.servers")}</a>
            <a href="#security">{t("footer.security")}</a>
          </div>
          <div>
            <Link to="/guide">{t("footer.guide")}</Link>
            <Link to="/faq">{t("footer.faq")}</Link>
            <Link to="/contacts">{t("footer.support")}</Link>
            {/*
            Два телеграма, и путать их нельзя: бот оформляет подписку, отдаёт
            доступ и принимает вопросы, канал — только новости. Бот стоит
            первым: это единственная из двух ссылок, по которой что-то
            делают, а не читают.

            Раньше поддержка была отдельным аккаунтом живого человека. Теперь
            это тот же бот: одно окно на всё — человеку не приходится
            выбирать, куда писать, а обращение сразу попадает туда, где видно
            его подписку.
            */}
            <a href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
              {t("footer.bot")}
            </a>
            <a href={NEWS_TELEGRAM} target="_blank" rel="noreferrer">
              {t("footer.channel")}
            </a>
          </div>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
            <Link to="/contacts">{t("footer.contacts")}</Link>
            {/* Почта рядом с телеграмом: писать в мессенджер готовы не все,
                а платёжные вопросы всё равно приходят письмом. */}
            <a href={SUPPORT_MAILTO}>{t("footer.email")}</a>
          </div>
          {/* В кабинет, а не на форму входа: вошедшего она отправляла
              вводить логин заново, хотя он уже вошёл. Гостя туда же не
              пустит Private и вернёт сюда после входа. */}
          <div className="sf-stores">
            <Link to="/account?tab=setup" className="btn btn-dark sf-store">
              <Picture src="/assets/ic-appstore.png" />
              App Store
            </Link>
            <Link to="/account?tab=setup" className="btn btn-dark sf-store">
              <Picture src="/assets/ic-googleplay.png" />
              Google Play
            </Link>
          </div>
        </div>

        <div className="sf-contact">
          <a href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
            {SUPPORT_TELEGRAM_NAME}
          </a>
          <a href={SUPPORT_MAILTO}>{SUPPORT_EMAIL}</a>
          <span>{t("footer.supportNote")}</span>
        </div>

        <div className="sf-bottom">
          <span>© {new Date().getFullYear()} Prosto VPN</span>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
