import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { FaqList } from "../components/FaqList.jsx";
import { SUPPORT_CHAT } from "../lib/contacts.js";
import { useI18n } from "../lib/i18n/index.jsx";
import "./faq.css";

/** Страница /faq: шапка как у правовых страниц, ниже — общий список с поиском. */
export function Faq() {
  const { t } = useI18n();

  return (
    <div className="fp">
      <SiteHeader />
      <section className="fp-hero">
        <div className="wrap">
          <Reveal className="fp-hero-in">
            <span className="fp-eyebrow">{t("faq.eyebrow")}</span>
            <h1>{t("faq.title")}</h1>
            <p>{t("faq.lead")}</p>
          </Reveal>
        </div>
      </section>

      <section className="fp-body">
        <div className="wrap fp-body-in">
          <FaqList />

          <Reveal className="fp-cta">
            <span>{t("faq.notFound")}</span>
            <div className="fp-cta-acts">
              <a className="btn btn-primary" href={SUPPORT_CHAT} target="_blank" rel="noreferrer">
                {t("faq.write")}
              </a>
              <Link to="/guide" className="fp-cta-link">
                {t("footer.guide")}
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
