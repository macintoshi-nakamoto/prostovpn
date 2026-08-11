import { Link } from "react-router-dom";
import "./site-footer.css";

/** Подвал лендинга: навигация, контакт поддержки, копирайт. Из макета. */
export function SiteFooter() {
  return (
    <footer className="sf">
      <div className="wrap sf-in">
        <img className="sf-logo" src="/assets/logo.png" alt="PROSTO" />

        <div className="sf-cols">
          <div>
            <a href="#plans">Тарифы</a>
            <a href="#app">Приложение</a>
            <a href="#speed">Серверы</a>
            <a href="#security">Безопасность</a>
          </div>
          <div>
            <Link to="/faq">FAQ</Link>
            <Link to="/contacts">Поддержка</Link>
            <a href="https://t.me/prosto_vpn_supp" target="_blank" rel="noreferrer">
              Telegram
            </a>
          </div>
          <div>
            <Link to="/terms">Условия</Link>
            <Link to="/privacy">Конфиденциальность</Link>
            <Link to="/contacts">Контакты</Link>
          </div>
          <div className="sf-stores">
            <Link to="/login" className="btn btn-dark sf-store">
              <img src="/assets/ic-appstore.png" alt="" />
              App Store
            </Link>
            <Link to="/login" className="btn btn-dark sf-store">
              <img src="/assets/ic-googleplay.png" alt="" />
              Google Play
            </Link>
          </div>
        </div>

        <div className="sf-contact">
          <a href="https://t.me/prosto_vpn_supp" target="_blank" rel="noreferrer">
            @prosto_vpn_supp
          </a>
          <span>Поддержка в Telegram отвечает быстро — в среднем за несколько минут</span>
        </div>

        <div className="sf-bottom">
          <span>© {new Date().getFullYear()} Prosto VPN</span>
          <div>
            <Link to="/terms">Условия</Link>
            <Link to="/privacy">Конфиденциальность</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
