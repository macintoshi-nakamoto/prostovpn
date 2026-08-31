import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal, ArtImage } from "../components/Reveal.jsx";
import { HeroOrbit } from "../components/HeroOrbit.jsx";
import { useSession } from "../lib/session.jsx";
import { useTilt } from "../lib/hooks";
import { useAnchorReveal } from "../lib/anchors";
import { api } from "../lib/api";
import { capitalize, useI18n } from "../lib/i18n/index.jsx";
import "./landing.css";
import { introApplies } from "../lib/plans.js";

const FEATURES = [
  { icon: "ic-arc.png", key: "speed", plain: true },
  { icon: "ic-territory-2.png", key: "countries" },
  { icon: "ic-devices-2.png", key: "devices" },
  { icon: "ic-mask-2.png", key: "logs" },
];

const DOC_LINKS = ["/privacy", "/terms", "/faq", "/contacts"];

const PLAN_TAB = "/account/subscription";

function termLabel(days, t) {
  if (days >= 365 && days % 365 === 0) {
    return t("units.years", { count: days / 365 });
  }
  if (days >= 28) {
    return t("units.months", { count: Math.round(days / 30) });
  }
  return t("units.days", { count: days });
}

function limitsOf(plan, t, f) {
  return [
    plan.traffic_limit_bytes == null
      ? t("landing.plans.unlimited")
      : t("landing.plans.traffic", { size: f.bytes(plan.traffic_limit_bytes) }),
    t("units.devices", { count: plan.device_limit }),
    t("units.countries", { count: plan.server_limit }),
  ];
}

function toCards(list, t, f) {
  const paid = list
    .filter((plan) => plan.price_kopecks > 0)
    .sort((a, b) => a.duration_days - b.duration_days);

  const cards = paid.map((plan) => {
    const monthly = plan.duration_days >= 60;
    const months = Math.max(1, Math.round(plan.duration_days / 30));
    // Вводная цена — это то, что человек заплатит сегодня, поэтому крупно
    // стоит она, а обычная уходит в подпись. Раньше витрина называла 249 ₽,
    // счёт выставлялся на 50 ₽, и цифры на экране не сходились ни с чем.
    const intro = introApplies(plan);
    const perMonth = intro
      ? plan.intro_price_kopecks
      : monthly
        ? Math.round(plan.price_kopecks / months)
        : plan.price_kopecks;
    const full = f.moneyFromKopecks(plan.price_kopecks, plan.currency);
    const term = termLabel(plan.duration_days, t);
    return {
      code: plan.code,
      term,

      per: intro
        ? t("landing.plans.introPer")
        : monthly
          ? t("landing.plans.perMonth")
          : t(plan.duration_days === 1 ? "landing.plans.perDay" : "landing.plans.perTerm"),
      monthly,
      perMonth: f.moneyFromKopecks(perMonth, plan.currency),
      perMonthValue: perMonth,
      note: intro
        ? t("landing.plans.introNote", { price: full })
        : plan.tagline || t("landing.plans.priceFor", { price: full, term }),
      limits: limitsOf(plan, t, f),
      featured: false,
    };
  });

  if (cards.length > 1) {
    const longest = cards[cards.length - 1];
    longest.featured = true;

    const shortest = cards.find((card) => card.monthly);
    if (shortest && longest.monthly && shortest !== longest) {
      const off = Math.round((1 - longest.perMonthValue / shortest.perMonthValue) * 100);
      if (off >= 5) longest.badge = `−${off}%`;
    }
  }

  const free = list.find((plan) => plan.price_kopecks === 0);
  const trial = free
    ? {
        title: t("landing.plans.trialTitle"),
        term: termLabel(free.duration_days, t),
        traffic:
          free.traffic_limit_bytes == null
            ? t("landing.plans.unlimitedShort")
            : t("landing.plans.traffic", { size: f.bytes(free.traffic_limit_bytes) }),
        note: free.tagline,
      }
    : null;

  const devices = Math.max(0, ...list.map((plan) => plan.device_limit || 0));

  return { cards, trial, devices };
}

const GB = 1024 * 1024 * 1024;
const FALLBACK_PLANS = [
  { code: "basic", duration_days: 30, price_kopecks: 24900, intro_price_kopecks: 5000, intro_applies: true, currency: "RUB", traffic_limit_bytes: 250 * GB, device_limit: 2, server_limit: 3 },
  { code: "3months", duration_days: 90, price_kopecks: 49900, currency: "RUB", traffic_limit_bytes: null, device_limit: 4, server_limit: 3 },
  { code: "preyear", duration_days: 180, price_kopecks: 89900, currency: "RUB", traffic_limit_bytes: null, device_limit: 6, server_limit: 3 },
  { code: "year", duration_days: 365, price_kopecks: 149900, currency: "RUB", traffic_limit_bytes: null, device_limit: 10, server_limit: 3 },
  { code: "trial", duration_days: 7, price_kopecks: 0, currency: "RUB", traffic_limit_bytes: 10 * GB, device_limit: 1, server_limit: 3 },
];

function Feature({ icon, plain, title, text, delay }) {
  const tilt = useTilt(9);
  return (
    <Reveal className="ld-feature" delay={delay}>
      <div className="ld-feature-in tilt tilt-glow" ref={tilt}>
        <ArtImage
          src={`/assets/${icon}`}
          className={`ld-feature-art${plain ? "" : " ld-feature-shadow"}`}
          speed={0.05}
          delay={delay + 90}
        />
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
    </Reveal>
  );
}

export function Landing() {
  const { t, raw, f } = useI18n();
  const { authed } = useSession();
  const [plans, setPlans] = useState(null);

  useAnchorReveal();

  useEffect(() => {
    let alive = true;
    api
      .plans()
      .then((list) => {
        if (!alive || !Array.isArray(list) || list.length === 0) return;
        if (!list.some((plan) => plan.price_kopecks > 0)) return;
        setPlans(list);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const { cards, trial, devices } = useMemo(
    () => toCards(plans || FALLBACK_PLANS, t, f),
    [plans, t, f],
  );

  const devicesLabel = t("landing.upTo", { value: t("units.devicesGen", { count: devices }) });
  const devicesTitle = capitalize(devicesLabel);

  return (
    <div className="ld">
      <SiteHeader />

      <section id="top" className="ld-hero">
        <div className="ld-hero-glow" aria-hidden="true" />
        <HeroOrbit />
        <div className="wrap ld-hero-in">
          <div className="ld-hero-body">
            <h1>
              <Reveal as="span" className="ld-hero-line" delay={60}>
                {t("landing.hero.line1")}
              </Reveal>
              <Reveal as="span" className="ld-hero-line" delay={180}>
                {t("landing.hero.line2")}
              </Reveal>
            </h1>
            <Reveal as="p" delay={340}>
              {t("landing.hero.lead")}
            </Reveal>
            <Reveal className="ld-hero-cta" delay={440}>
              <a href="#plans" className="btn ld-hero-primary">
                {t("landing.hero.primary")}
              </a>
              <a href="#app" className="btn ld-hero-ghost">
                {t("landing.hero.ghost")}
              </a>
            </Reveal>
            <Reveal as="span" className="ld-hero-plats" delay={560}>
              {t("landing.hero.platforms")}
            </Reveal>
          </div>
        </div>
      </section>

      <section className="ld-features">
        <div className="wrap ld-features-grid">
          {FEATURES.map((feature, i) => (
            <Feature
              key={feature.key}
              icon={feature.icon}
              plain={feature.plain}
              title={
                feature.key === "devices"
                  ? devicesTitle
                  : t(`landing.features.${feature.key}.title`)
              }
              text={t(`landing.features.${feature.key}.text`)}
              delay={i * 110}
            />
          ))}
        </div>
      </section>

      <section id="speed" className="ld-zero">
        <ArtImage
          className="ld-zero-obj ld-zero-left"
          src="/assets/obj-ruble-lock.png"
          speed={0.22}
          rotate={0.9}
        />
        <ArtImage
          className="ld-zero-obj ld-zero-right"
          src="/assets/obj-platforms.png"
          speed={-0.16}
          rotate={-1.1}
          delay={120}
        />
        <Reveal className="ld-zero-in" variant="zoom">
          <div className="ld-zero-num">0</div>
          <h2>
            {t("landing.zero.title")}
            <br />
            <span>{t("landing.zero.subtitle")}</span>
          </h2>
          <p>{t("landing.zero.text")}</p>
          <a href="#plans" className="btn btn-primary ld-zero-btn">
            {t("landing.zero.button")}
          </a>
        </Reveal>
      </section>

      <section id="app" className="ld-app">
        <div className="wrap ld-app-grid">
          <Reveal className="ld-app-body">
            <h2>
              {t("landing.app.line1")}
              <br />
              {t("landing.app.line2")}
              <br />
              {t("landing.app.line3")}
            </h2>
            <p>{t("landing.app.text")}</p>
            <div className="ld-app-stores">
              <Link to="/guide" className="btn btn-dark ld-store">
                {t("landing.app.button")}
              </Link>
            </div>
          </Reveal>
          <div className="ld-app-art">
            <div className="ld-app-halo" aria-hidden="true" />
            <ArtImage
              className="ld-app-laptop"
              src="/assets/obj-laptop-orange.png"
              alt={t("landing.app.laptopAlt")}
              speed={0.1}
              float={false}
            />
          </div>
        </div>
      </section>

      <section id="split" className="ld-split">
        <div className="ld-split-deco" aria-hidden="true">
          <ArtImage className="ld-split-ribbon" src="/assets/ribbon-diagonal.png" speed={-0.2} rotate={-1.4} float={false} />
          <ArtImage className="ld-split-badge ld-split-badge-1" src="/assets/logo-t.png" width={208} height={221} speed={0.1} rotate={1.8} />
          <ArtImage className="ld-split-badge ld-split-badge-2" src="/assets/logo-vk.png" width={256} height={189} speed={0.18} rotate={-1.6} delay={100} />
        </div>
        <div className="wrap ld-split-in">
          <Reveal className="ld-split-head">
            <h2>
              {t("landing.split.line1")}
              <br />
              {t("landing.split.line2")}
            </h2>
            <p>{t("landing.split.text")}</p>
          </Reveal>
          <div className="ld-split-cards">
            {raw("landing.split.cards").map((c, i) => (
              <Reveal className="ld-split-card" key={c.title} delay={i * 70}>
                <h3>{c.title}</h3>
                <p>{c.text}</p>
              </Reveal>
            ))}
          </div>
          <Reveal className="ld-split-note">
            <span>{t("landing.split.note")}</span>
            <a href="#plans" className="btn btn-primary ld-split-note-btn">
              {t("landing.split.button")}
            </a>
          </Reveal>
        </div>
      </section>

      <section id="plans" className="ld-plans">
        <ArtImage className="ld-plans-ribbon" src="/assets/ribbon-spiral.png" speed={0.24} rotate={-2} />
        <div className="wrap ld-plans-in">
          <Reveal className="ld-plans-head">
            <h2>
              {t("landing.plans.line1")}
              <br />
              {t("landing.plans.line2")}
            </h2>
            <p>{t("landing.plans.lead")}</p>
          </Reveal>

          {trial && (
            <Reveal className="ld-trial">
              <div className="ld-trial-body">
                <span className="ld-trial-tag">{t("landing.plans.trialTag")}</span>
                <h3>
                  {t("landing.plans.trialHead", {
                    title: trial.title,
                    term: trial.term,
                    traffic: trial.traffic,
                  })}
                </h3>
                <p>{trial.note || t("landing.plans.trialNote")}</p>
              </div>
              <Link
                to={authed ? PLAN_TAB : "/login?mode=signup"}
                className="btn btn-primary ld-trial-btn"
              >
                {authed ? t("landing.plans.trialButtonAuthed") : t("landing.plans.trialButton")}
              </Link>
            </Reveal>
          )}

          <div
            className="ld-plans-grid"
            style={{ "--plan-count": Math.min(cards.length, 5) }}
            data-dense={cards.length >= 5 ? "" : undefined}
          >
            {cards.map((p, i) => (
              <Reveal
                className={`ld-plan${p.featured ? " ld-plan-featured" : ""}`}
                key={p.code || p.term}
                delay={i * 90}
              >
                {p.badge && <span className="ld-plan-badge">{p.badge}</span>}
                <span className="ld-plan-term">{p.term}</span>
                <div className="ld-plan-price">
                  <span className="ld-plan-sum">{p.perMonth}</span>
                  <span className="ld-plan-per">{p.per || t("landing.plans.perMonth")}</span>
                </div>
                <p className="ld-plan-note">{p.note}</p>
                <ul className="ld-plan-limits">
                  {p.limits.map((limit) => (
                    <li key={limit}>{limit}</li>
                  ))}
                </ul>
                <Link
                  to={`${PLAN_TAB}?plan=${encodeURIComponent(p.code || "")}`}
                  className={`btn ld-plan-btn ${p.featured ? "btn-primary" : "btn-outline"}`}
                >
                  {t("landing.plans.choose")}
                </Link>
              </Reveal>
            ))}
          </div>

          <Reveal className="ld-plans-fine" delay={120}>
            {t("landing.plans.fine")}
          </Reveal>
        </div>
      </section>

      <section id="security" className="ld-shield">
        <div className="wrap ld-shield-grid">
          <Reveal className="ld-shield-body">
            <h2>
              {t("landing.shield.line1")}
              <br />
              {t("landing.shield.line2")}
            </h2>
            <div className="ld-shield-list">
              {raw("landing.shield.items").map((item) => (
                <div key={item.title}>
                  <h3>{item.title}</h3>
                  <p>{item.text}</p>
                </div>
              ))}
            </div>
            <Link to="/faq" className="btn ld-shield-btn">
              {t("landing.shield.button")}
            </Link>
          </Reveal>
          <div className="ld-shield-art">
            <div className="ld-shield-halo" aria-hidden="true" />
            <ArtImage className="ld-shield-obj" src="/assets/obj-case-2.png" speed={0.14} rotate={0.8} />
          </div>
        </div>
      </section>

      <section className="ld-devices">
        <ArtImage className="ld-devices-phone" src="/assets/obj-iphone-side.png" speed={0.3} rotate={1.2} />
        <div className="wrap ld-devices-in">
          <Reveal className="ld-devices-body">
            <h3>{t("landing.devices.title")}</h3>
            <p>{t("landing.devices.text", { devices: devicesLabel })}</p>
          </Reveal>
          <Reveal className="ld-devices-tags" delay={120}>
            {["iOS", "Android", "macOS", "Windows", "TV"].map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </Reveal>
        </div>
      </section>

      <section id="docs" className="ld-docs">
        <ArtImage className="ld-docs-ribbon" src="/assets/ribbon-wave.png" speed={-0.22} rotate={1.5} />
        <div className="wrap ld-docs-in">
          <Reveal className="ld-docs-head">
            <h2>
              {t("landing.docs.line1")}
              <br />
              {t("landing.docs.line2")}
            </h2>
            <p>{t("landing.docs.lead")}</p>
          </Reveal>
          <div className="ld-docs-grid">
            {raw("landing.docs.items").map((d, i) => (
              <Reveal as="div" key={d.title} delay={i * 70}>
                <Link to={DOC_LINKS[i]} className="ld-docs-card">
                  <span>
                    <span className="ld-docs-title">{d.title}</span>
                    <span className="ld-docs-sub">{d.text}</span>
                  </span>
                  <span className="ld-docs-chev">›</span>
                </Link>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section id="privacy" className="ld-privacy">
        <div className="wrap ld-privacy-in">
          <Reveal className="ld-privacy-head">
            <span className="ld-privacy-eyebrow">{t("landing.privacy.eyebrow")}</span>
            <h2>
              {t("landing.privacy.line1")}
              <br />
              {t("landing.privacy.line2")}
            </h2>
          </Reveal>
          <Reveal className="ld-privacy-body" delay={90}>
            {raw("landing.privacy.items").map((text) => (
              <p key={text}>{text}</p>
            ))}
            <span className="ld-privacy-sign">{t("landing.privacy.sign")}</span>
          </Reveal>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
