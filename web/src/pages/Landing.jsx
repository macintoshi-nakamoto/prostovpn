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

/*
 * Три плитки из четырёх — про сеть и её устройство, они не зависят от
 * тарифов. Четвёртая, про устройства, зависит: сколько их разрешено,
 * решает тариф в панели, и написать здесь число значит однажды разойтись
 * с карточками, которые стоят ниже на этой же странице.
 *
 * В массиве только картинка и ключ: подписи живут в словаре, иначе они не
 * переводятся.
 */
const FEATURES = [
  { icon: "ic-arc.png", key: "speed", plain: true },
  { icon: "ic-territory-2.png", key: "countries" },
  { icon: "ic-devices-2.png", key: "devices" },
  { icon: "ic-mask-2.png", key: "logs" },
];

/** Адреса документов — рядом с порядком карточек в словаре. */
const DOC_LINKS = ["/privacy", "/terms", "/faq", "/contacts"];

/*
 * Кнопки действия ведут в кабинет, а не на форму входа.
 *
 * Раньше здесь стояло `/login` у всех до единой, и вошедший человек, нажав
 * «Выбрать» на тарифе, снова видел форму входа — при том, что шапка той же
 * страницы уже показывала ему «Кабинет». Теперь адрес один для всех: гостя
 * до кабинета не пустит Private из App.jsx, отправит на вход и после него
 * вернёт ровно сюда, вместе с выбранным тарифом в запросе.
 */
const PLAN_TAB = "/account/subscription";

/** «30 дней» → «1 месяц», «365 дней» → «1 год»: срок словами, а не в днях. */
function termLabel(days, t) {
  if (days >= 365 && days % 365 === 0) {
    return t("units.years", { count: days / 365 });
  }
  if (days >= 28) {
    return t("units.months", { count: Math.round(days / 30) });
  }
  return t("units.days", { count: days });
}

/**
 * Что тариф разрешает: трафик, устройства, страны.
 *
 * Все три числа живут в панели, и все три человек ищет глазами до того, как
 * нажмёт «Выбрать». Пустого лимита трафика не бывает: отсутствие числа —
 * это и есть безлимит, так и написано.
 */
function limitsOf(plan, t, f) {
  return [
    plan.traffic_limit_bytes == null
      ? t("landing.plans.unlimited")
      : t("landing.plans.traffic", { size: f.bytes(plan.traffic_limit_bytes) }),
    t("units.devices", { count: plan.device_limit }),
    t("units.countries", { count: plan.server_limit }),
  ];
}

/**
 * Тарифы для карточек.
 *
 * Берём настоящие из панели: там их и заводят, и правят цены, сроки, трафик
 * и число устройств. Ни одного из этих чисел в вёрстке нет — иначе счёт на
 * оплату и обещание на странице однажды разойдутся.
 *
 * Цену показываем за месяц: длинный тариф так выигрышнее читается, а полная
 * сумма уходит в подпись под ней.
 *
 * Бесплатный тариф в общий ряд не ставим. Он не продаётся — его выдаёт
 * регистрация, — и кнопка «Выбрать» вела бы в платёжную форму на ноль
 * рублей. Ему своя полоса над карточками.
 */
function toCards(list, t, f) {
  const paid = list
    .filter((plan) => plan.price_kopecks > 0)
    .sort((a, b) => a.duration_days - b.duration_days);

  const cards = paid.map((plan) => {
    const months = Math.max(1, Math.round(plan.duration_days / 30));
    const perMonth = Math.round(plan.price_kopecks / months);
    const full = f.moneyFromKopecks(plan.price_kopecks, plan.currency);
    const term = termLabel(plan.duration_days, t);
    return {
      code: plan.code,
      term,
      perMonth: f.moneyFromKopecks(perMonth, plan.currency),
      perMonthValue: perMonth,
      note: plan.tagline || t("landing.plans.priceFor", { price: full, term }),
      limits: limitsOf(plan, t, f),
      featured: false,
    };
  });

  if (cards.length > 1) {
    /*
    Выделяем самый длинный срок — ровно то, о чём говорит заголовок секции:
    «чем длиннее срок, тем ниже цена месяца». Брать самый дешёвый месяц
    нельзя: дешевле всех может оказаться начальный тариф, и он дешёвый не
    из-за срока, а из-за лимитов, — выделять его как выгодный было бы
    неправдой.
    */
    const longest = cards[cards.length - 1];
    longest.featured = true;

    // Бейдж со скидкой — только если месяц действительно дешевле, чем на
    // самом коротком тарифе. Нет выгоды — нет и обещания.
    const shortest = cards[0];
    const off = Math.round((1 - longest.perMonthValue / shortest.perMonthValue) * 100);
    if (off >= 5) longest.badge = `−${off}%`;
  }

  const free = list.find((plan) => plan.price_kopecks === 0);
  const trial = free
    ? {
        /*
        Заголовок пробной полосы берём из словаря, а не из панели.

        В панели у бесплатного тарифа стоит «Пробный», и подставляется он в
        середину фразы: «Пробный: 2 дня и 10 ГБ трафика». По-русски это ещё
        читается, а в английском получалось «Пробный: 2 days and 10 GB of
        traffic» — русское слово посреди английского предложения. Название
        здесь не имя продукта, а роль карточки, и знаем мы её сами; всё
        остальное на карточке — сроки, трафик, текст под заголовком — как было,
        из панели.
        */
        title: t("landing.plans.trialTitle"),
        term: termLabel(free.duration_days, t),
        traffic:
          free.traffic_limit_bytes == null
            ? t("landing.plans.unlimitedShort")
            : t("landing.plans.traffic", { size: f.bytes(free.traffic_limit_bytes) }),
        note: free.tagline,
      }
    : null;

  // Сколько устройств обещать в плитке преимуществ: столько, сколько даёт
  // самый щедрый тариф, — меньшие числа стоят на своих карточках.
  const devices = Math.max(0, ...list.map((plan) => plan.device_limit || 0));

  return { cards, trial, devices };
}

/*
 * Что показать, пока панель не ответила.
 *
 * Пустая секция цен хуже ориентировочной: человек уходит, не узнав порядок
 * сумм. Значения здесь — те же, что заведены в панели, и живут ровно до
 * первого успешного ответа.
 *
 * Это сырые тарифы, а не готовые карточки: подписи к ним собирает тот же
 * toCards, что и для настоящих, — иначе запасные пришлось бы переводить
 * отдельно и они разошлись бы с боевыми при первой же правке.
 */
const GB = 1024 * 1024 * 1024;
const FALLBACK_PLANS = [
  { code: "basic", duration_days: 30, price_kopecks: 19900, currency: "RUB", traffic_limit_bytes: 250 * GB, device_limit: 2, server_limit: 3 },
  { code: "3months", duration_days: 90, price_kopecks: 49900, currency: "RUB", traffic_limit_bytes: null, device_limit: 4, server_limit: 3 },
  { code: "preyear", duration_days: 180, price_kopecks: 89900, currency: "RUB", traffic_limit_bytes: null, device_limit: 6, server_limit: 3 },
  { code: "year", duration_days: 365, price_kopecks: 149900, currency: "RUB", traffic_limit_bytes: null, device_limit: 10, server_limit: 3 },
  { code: "trial", duration_days: 2, price_kopecks: 0, currency: "RUB", traffic_limit_bytes: 10 * GB, device_limit: 1, server_limit: 3 },
];

/**
 * Карточка преимущества.
 *
 * Иконка выходит из размытия с поворотом, карточка отзывается на курсор
 * наклоном и подсветкой — четыре одинаковых блока перестают быть просто
 * рядом картинок.
 */
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
        // Панель недоступна или платных тарифов нет — остаются запасные
        // значения: пустая секция цен хуже, чем ориентировочная.
        if (!alive || !Array.isArray(list) || list.length === 0) return;
        if (!list.some((plan) => plan.price_kopecks > 0)) return;
        setPlans(list);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Пересобираем подписи при смене языка: числа те же, слова вокруг них —
  // другие. t и f меняются только вместе с языком, лишних пересчётов нет.
  const { cards, trial, devices } = useMemo(
    () => toCards(plans || FALLBACK_PLANS, t, f),
    [plans, t, f],
  );

  // Число устройств в плитке преимуществ и в секции про устройства —
  // из панели: два места на странице не должны обещать разное. Плитке нужна
  // прописная: она стоит в ряду с «До 1 Гбит/с» и «60+ стран», а в середине
  // предложения ниже прописная была бы ошибкой.
  const devicesLabel = t("landing.upTo", { value: t("units.devicesGen", { count: devices }) });
  const devicesTitle = capitalize(devicesLabel);

  return (
    <div className="ld">
      <SiteHeader />

      {/* Герой */}
      <section id="top" className="ld-hero">
        <div className="ld-hero-glow" aria-hidden="true" />
        <HeroOrbit />
        <div className="wrap ld-hero-in">
          {/*
          Строки заголовка появляются по очереди, а не блоком: так герой
          «набирается» на глазах и держит взгляд первые полторы секунды.
          */}
          <div className="ld-hero-body">
            <h1>
              <Reveal as="span" className="ld-hero-line" delay={60}>
                {t("landing.hero.line1")}
              </Reveal>
              <Reveal as="span" className="ld-hero-line" delay={180}>
                {t("landing.hero.line2")}
              </Reveal>
            </h1>
            {/*
            «Без лимитов трафика» отсюда убрано намеренно: лимит есть на
            начальном тарифе и на пробном периоде, и обещать обратное в
            первом же абзаце значит спорить с собственными карточками,
            которые стоят ниже на этой же странице.
            */}
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

      {/* Четыре преимущества */}
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

      {/* Ноль записей */}
      <section id="speed" className="ld-zero">
        {/* Объекты по краям едут против прокрутки и слегка поворачиваются —
            секция получает глубину, а не просто «две картинки по бокам». */}
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

      {/* Приложение */}
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
            {/* Одна кнопка вместо двух витрин магазинов: приложений в App
                Store и Google Play нет — Android ставится файлом с сайта, на
                iPhone подключаются ключом. Ведёт в инструкцию, где для каждой
                платформы свои шаги и живая ссылка на установщик. */}
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

      {/* Российские сервисы */}
      <section id="split" className="ld-split">
        <div className="ld-split-deco" aria-hidden="true">
          <ArtImage className="ld-split-ribbon" src="/assets/ribbon-diagonal.png" speed={-0.2} rotate={-1.4} float={false} />
          {/*
          У бейджей проставлены настоящие размеры файлов, и это не украшение
          разметки. Ширину задаёт css, высота — auto; пока картинка не
          загрузилась и пропорция неизвестна, высота считается нулевой, а у
          пустой коробки доля пересечения всегда 0 — наблюдатель появления
          не срабатывает и бейдж навсегда остаётся прозрачным. С width/height
          пропорция известна сразу, до загрузки.

          Ход параллакса у первого меньше соседей: он стоит у верхнего края
          секции, а она обрезает содержимое — см. .ld-split-badge-1 в css.
          */}
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

      {/* Тарифы */}
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

          {/*
          Пробный период стоит перед платными карточками и выглядит иначе:
          его не покупают, его получают регистрацией. Одинаковая карточка с
          кнопкой «Выбрать» вела бы в платёжную форму на ноль рублей.
          */}
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
              {/*
              Пробный период получают регистрацией, поэтому гостя ведём
              сразу на её вкладку, а не на форму входа: учётки у него ещё
              нет. Вошедшему предлагать «попробовать» нечего — он уже внутри,
              и кнопка открывает его тариф.
              */}
              <Link
                to={authed ? PLAN_TAB : "/login?mode=signup"}
                className="btn btn-primary ld-trial-btn"
              >
                {authed ? t("landing.plans.trialButtonAuthed") : t("landing.plans.trialButton")}
              </Link>
            </Reveal>
          )}

          <div className="ld-plans-grid">
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
                  <span className="ld-plan-per">{t("landing.plans.perMonth")}</span>
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

      {/* Щит */}
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

      {/* Одна подписка — все устройства */}
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

      {/* Прозрачно во всём */}
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

      {/*
      Приватность — последним блоком перед подвалом.

      Не карточки с иконками: обещание «мы вас не сдадим» тем убедительнее,
      чем меньше вокруг него оформления. Поэтому чёрная лента, крупное
      утверждение слева и три коротких абзаца справа — прочитывается за
      двадцать секунд, а не разглядывается.
      */}
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
