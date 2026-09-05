import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import { SUPPORT_CHAT } from "../lib/contacts.js";
import "./legal.css";

const DOC_KEYS = ["faq", "terms", "privacy", "contacts"];

export function Legal({ doc }) {
  const { t, raw } = useI18n();
  const key = DOC_KEYS.includes(doc) ? doc : "faq";
  const page = {
    eyebrow: t(`legal.${key}.eyebrow`),
    title: t(`legal.${key}.title`),
    lead: t(`legal.${key}.lead`),
    blocks: raw(`legal.${key}.blocks`),
  };

  return (
    <div className="lgl">
      <SiteHeader />
      <section className="lgl-hero">
        <div className="wrap">
          <Reveal className="lgl-hero-in">
            <span className="lgl-eyebrow">{page.eyebrow}</span>
            <h1>{page.title}</h1>
            <p>{page.lead}</p>
          </Reveal>
        </div>
      </section>

      <section className="lgl-body">
        <div className="wrap lgl-body-in">
          {page.blocks.map((block, bi) => (
            <Reveal className="lgl-block" key={block.h} delay={bi * 60}>
              <h2>{block.h}</h2>
              <div className="lgl-items">
                {block.items.map(([h, text]) => (
                  <div className="lgl-item" key={h}>
                    <h3>{h}</h3>
                    <p>{text}</p>
                  </div>
                ))}
              </div>
            </Reveal>
          ))}

          <Reveal className="lgl-cta">
            <span>{t("legal.notFoundAnswer")}</span>
            <a
              className="btn btn-primary"
              href={SUPPORT_CHAT}
              target="_blank"
              rel="noreferrer"
            >
              {t("legal.writeSupport")}
            </a>
            <Link to="/" className="lgl-back">
              {t("legal.back")}
            </Link>
          </Reveal>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
