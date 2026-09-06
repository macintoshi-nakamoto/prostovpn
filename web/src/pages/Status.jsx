import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { Flag } from "../components/Flags.jsx";
import { OK_MARK, BAD_MARK } from "../components/ServerStatus.jsx";
import { api } from "../lib/api";
import { SUPPORT_CHAT } from "../lib/contacts.js";
import { useI18n } from "../lib/i18n/index.jsx";
import "./status.css";

/**
 * Публичная страница состояния — prostovpn.cc/status.
 *
 * Та же полоска, что в кабинете, но без входа: человеку, у которого не
 * подключается, логичнее открыть адрес в браузере, чем вспоминать пароль.
 * Данные те же, что видит админ: живость отмечает обход за трафиком.
 */

const REFRESH_MS = 60_000;

function clock(iso, lang) {
  if (!iso) return "";
  const date = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(lang === "ru" ? "ru-RU" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function Status() {
  const { t, lang } = useI18n();
  const [status, setStatus] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.hidden) return;
      api
        .status()
        .then((r) => {
          if (!alive) return;
          setStatus(r);
          setFailed(false);
        })
        .catch(() => alive && setFailed(true));
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, []);

  const bad = Boolean(status && status.down > 0);
  let headline = t("status.loading");
  if (failed && !status) headline = t("status.unreachable");
  else if (status && !status.total) headline = t("status.empty");
  else if (status && bad) {
    headline =
      status.down === 1
        ? t("status.oneDown", {
            country:
              (status.servers.find((one) => !one.up) || {}).country || t("status.node"),
          })
        : t("status.manyDown", { n: status.down });
  } else if (status) headline = t("status.allUp");

  const checked = status ? clock(status.checked_at, lang) : "";

  return (
    <div className="sp">
      <SiteHeader />
      <section className={"sp-hero" + (bad ? " is-bad" : "")}>
        <div className="wrap">
          <Reveal className="sp-hero-in">
            <span className="sp-eyebrow">{t("status.title")}</span>
            <h1 className="sp-head">
              {status && status.total ? (
                <span className="sp-head-mark" aria-hidden="true">
                  {bad ? BAD_MARK : OK_MARK}
                </span>
              ) : null}
              <span>{headline}</span>
            </h1>
            <p>{t("status.pageLead")}</p>
          </Reveal>
        </div>
      </section>

      <section className="sp-body">
        <div className="wrap sp-body-in">
          <Reveal className="sp-card">
            {status && status.total ? (
              <div className="sp-list">
                {status.servers.map((one) => (
                  <div key={one.name} className="sp-row">
                    <span className="sp-flag">
                      <Flag code={one.country_code} title={one.country || one.name} />
                    </span>
                    <span className="sp-name">{one.country || one.name}</span>
                    <span className={"sp-state" + (one.up ? "" : " is-bad")}>
                      <i aria-hidden="true" />
                      {one.up ? t("status.up") : t("status.down")}
                      {!one.up && one.down_since ? (
                        <small>{t("status.since", { time: clock(one.down_since, lang) })}</small>
                      ) : null}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="sp-quiet">{headline}</p>
            )}
            {checked ? (
              <p className="sp-meta">
                {t("status.checked", { time: checked })} · {t("status.refresh")}
              </p>
            ) : null}
          </Reveal>

          <Reveal className="sp-cta" delay={60}>
            <div>
              <h2>{t("status.ctaTitle")}</h2>
              <p>{t("status.ctaText")}</p>
            </div>
            <div className="sp-cta-acts">
              <Link to="/guide" className="btn btn-primary">
                {t("status.ctaGuide")}
              </Link>
              <Link to="/blocks" className="sp-cta-link">
                {t("status.ctaBlocks")}
              </Link>
              <a className="sp-cta-link" href={SUPPORT_CHAT} target="_blank" rel="noreferrer">
                {t("status.ctaSupport")}
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
