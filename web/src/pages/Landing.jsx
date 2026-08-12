import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal, ArtImage } from "../components/Reveal.jsx";
import { HeroOrbit } from "../components/HeroOrbit.jsx";
import { Picture } from "../components/Picture.jsx";
import { useTilt } from "../lib/hooks";
import { useAnchorReveal } from "../lib/anchors";
import { api } from "../lib/api";
import { bytes, moneyFromKopecks, plural } from "../lib/format";
import "./landing.css";

/*
 * Три плитки из четырёх — про сеть и её устройство, они не зависят от
 * тарифов. Четвёртая, про устройства, зависит: сколько их разрешено,
 * решает тариф в панели, и написать здесь число значит однажды разойтись
 * с карточками, которые стоят ниже на этой же странице.
 */
const FEATURES = [
  { icon: "ic-arc.png", title: "До 1 Гбит/с", text: "Скорость не режется даже в час пик", plain: true },
  { icon: "ic-territory-2.png", title: "60+ стран", text: "Более 900 серверов на пяти континентах" },
  { icon: "ic-devices-2.png", key: "devices", title: "5 устройств", text: "Одна подписка на всю семью" },
  { icon: "ic-mask-2.png", title: "Без логов", text: "Мы не храним историю ваших подключений" },
];

const BYPASS = [
  { title: "Банки", text: "Приложения и переводы открываются без ошибок геолокации" },
  { title: "Маркетплейсы", text: "Заказы, оплата и доставка работают в обычном режиме" },
  { title: "Госуслуги", text: "Вход по СМС и подтверждения проходят с первого раза" },
  { title: "Такси и доставка", text: "Карты и адреса определяются по вашему реальному городу" },
];

const SHIELD = [
  {
    title: "Шифрование AES-256",
    text: "Тот же стандарт, что используют банки. Протоколы WireGuard и OpenVPN на выбор.",
  },
  {
    title: "Защита от утечек DNS",
    text: "Запросы уходят только через туннель: провайдер не видит, какие сайты вы открываете.",
  },
  {
    title: "Независимый аудит",
    text: "Инфраструктуру и политику отсутствия логов ежегодно проверяет внешняя команда.",
  },
];

const DOCS = [
  { title: "Политика без логов", text: "Какие данные мы не собираем и почему", to: "/privacy" },
  { title: "Условия подписки", text: "Оплата, продление и возврат средств", to: "/terms" },
  { title: "FAQ", text: "Как работает VPN и что делать при сбоях", to: "/faq" },
  { title: "Контакты", text: "Поддержка и обратная связь", to: "/contacts" },
];

/** «30 дней» → «1 месяц», «365 дней» → «1 год»: срок словами, а не в днях. */
function termLabel(days) {
  if (days >= 365 && days % 365 === 0) {
    const years = days / 365;
    return `${years} ${plural(years, ["год", "года", "лет"])}`;
  }
  if (days >= 28) {
    const months = Math.round(days / 30);
    return `${months} ${plural(months, ["месяц", "месяца", "месяцев"])}`;
  }
  return `${days} ${plural(days)}`;
}

/**
 * Что тариф разрешает: трафик, устройства, страны.
 *
 * Все три числа живут в панели, и все три человек ищет глазами до того, как
 * нажмёт «Выбрать». Пустого лимита трафика не бывает: отсутствие числа —
 * это и есть безлимит, так и написано.
 */
function limitsOf(plan) {
  const devices = plan.device_limit;
  const countries = plan.server_limit;
  return [
    plan.traffic_limit_bytes == null
      ? "Безлимитный трафик"
      : `${bytes(plan.traffic_limit_bytes)} трафика`,
    `${devices} ${plural(devices, ["устройство", "устройства", "устройств"])}`,
    `${countries} ${plural(countries, ["страна", "страны", "стран"])}`,
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
function toCards(list) {
  const paid = list
    .filter((plan) => plan.price_kopecks > 0)
    .sort((a, b) => a.duration_days - b.duration_days);

  const cards = paid.map((plan) => {
    const months = Math.max(1, Math.round(plan.duration_days / 30));
    const perMonth = Math.round(plan.price_kopecks / months);
    const full = moneyFromKopecks(plan.price_kopecks, plan.currency);
    const term = termLabel(plan.duration_days);
    return {
      code: plan.code,
      term,
      perMonth: moneyFromKopecks(perMonth, plan.currency),
      perMonthValue: perMonth,
      note: plan.tagline || `${full} за ${term}`,
      limits: limitsOf(plan),
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
        title: free.title,
        term: termLabel(free.duration_days),
        traffic:
          free.traffic_limit_bytes == null
            ? "без лимита трафика"
            : `${bytes(free.traffic_limit_bytes)} трафика`,
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
 */
const FALLBACK = {
  cards: [
    {
      code: "basic",
      term: "1 месяц",
      perMonth: "199 ₽",
      note: "199 ₽ за 1 месяц",
      limits: ["250 ГБ трафика", "2 устройства", "3 страны"],
      featured: false,
    },
    {
      code: "3months",
      term: "3 месяца",
      perMonth: "166 ₽",
      note: "499 ₽ за 3 месяца",
      limits: ["Безлимитный трафик", "4 устройства", "3 страны"],
      featured: false,
    },
    {
      code: "preyear",
      term: "6 месяцев",
      perMonth: "150 ₽",
      note: "899 ₽ за 6 месяцев",
      limits: ["Безлимитный трафик", "6 устройств", "3 страны"],
      featured: false,
    },
    {
      code: "year",
      term: "1 год",
      perMonth: "125 ₽",
      note: "1 499 ₽ за 1 год",
      limits: ["Безлимитный трафик", "10 устройств", "3 страны"],
      featured: true,
      badge: "−37%",
    },
  ],
  trial: { title: "Пробный период", term: "2 дня", traffic: "10 ГБ трафика", note: null },
  devices: 10,
};

/**
 * Карточка преимущества.
 *
 * Иконка выходит из размытия с поворотом, карточка отзывается на курсор
 * наклоном и подсветкой — четыре одинаковых блока перестают быть просто
 * рядом картинок.
 */
function Feature({ feature, delay }) {
  const tilt = useTilt(9);
  return (
    <Reveal className="ld-feature" delay={delay}>
      <div className="ld-feature-in tilt tilt-glow" ref={tilt}>
        <ArtImage
          src={`/assets/${feature.icon}`}
          className={`ld-feature-art${feature.plain ? "" : " ld-feature-shadow"}`}
          speed={0.05}
          delay={delay + 90}
        />
        <h3>{feature.title}</h3>
        <p>{feature.text}</p>
      </div>
    </Reveal>
  );
}

export function Landing() {
  const [{ cards, trial, devices }, setPlans] = useState(FALLBACK);

  useAnchorReveal();

  useEffect(() => {
    let alive = true;
    api
      .plans()
      .then((list) => {
        // Панель недоступна или тарифов нет — остаются запасные значения:
        // пустая секция цен хуже, чем ориентировочная.
        if (!alive || !Array.isArray(list) || list.length === 0) return;
        const next = toCards(list);
        if (next.cards.length === 0) return;
        setPlans(next);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Число устройств в плитке преимуществ и в секции про устройства —
  // из панели: два места на странице не должны обещать разное. Плитке нужна
  // прописная: она стоит в ряду с «До 1 Гбит/с» и «60+ стран», а в середине
  // предложения ниже прописная была бы ошибкой.
  const devicesLabel = `до ${devices} ${plural(devices, ["устройства", "устройств", "устройств"])}`;
  const devicesTitle = devicesLabel[0].toUpperCase() + devicesLabel.slice(1);

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
                Интернет
              </Reveal>
              <Reveal as="span" className="ld-hero-line" delay={180}>
                без границ
              </Reveal>
            </h1>
            {/*
            «Без лимитов трафика» отсюда убрано намеренно: лимит есть на
            начальном тарифе и на пробном периоде, и обещать обратное в
            первом же абзаце значит спорить с собственными карточками,
            которые стоят ниже на этой же странице.
            */}
            <Reveal as="p" delay={340}>
              Подключение в одно нажатие, 60+ стран и скорость до 1 Гбит/с. Без логов, без
              настроек и без ограничения скорости.
            </Reveal>
            <Reveal className="ld-hero-cta" delay={440}>
              <a href="#plans" className="btn ld-hero-primary">
                Начать использовать
              </a>
              <a href="#app" className="btn ld-hero-ghost">
                Как это работает
              </a>
            </Reveal>
            <Reveal as="span" className="ld-hero-plats" delay={560}>
              iOS · Android · macOS · Windows
            </Reveal>
          </div>
        </div>
      </section>

      {/* Четыре преимущества */}
      <section className="ld-features">
        <div className="wrap ld-features-grid">
          {FEATURES.map((f, i) => (
            <Feature
              key={f.title}
              feature={f.key === "devices" ? { ...f, title: devicesTitle } : f}
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
            записей
            <br />
            <span>о вашем трафике</span>
          </h2>
          <p>
            Серверы работают в оперативной памяти: после перезагрузки на них не остаётся
            ничего. Политику подтверждает независимый аудит.
          </p>
          <a href="#plans" className="btn btn-primary ld-zero-btn">
            Подключить Prosto VPN
          </a>
        </Reveal>
      </section>

      {/* Приложение */}
      <section id="app" className="ld-app">
        <div className="wrap ld-app-grid">
          <Reveal className="ld-app-body">
            <h2>
              Приложение,
              <br />
              которое просто
              <br />
              работает
            </h2>
            <p>
              Одна кнопка на главном экране. Всё остальное — автоматически: лучший сервер,
              обход блокировок и защита при переключении на Wi-Fi.
            </p>
            <div className="ld-app-stores">
              <Link to="/login" className="btn btn-dark ld-store">
                <Picture src="/assets/ic-appstore.png" />
                App Store
              </Link>
              <Link to="/login" className="btn btn-dark ld-store">
                <Picture src="/assets/ic-googleplay.png" />
                Google Play
              </Link>
            </div>
          </Reveal>
          <div className="ld-app-art">
            <div className="ld-app-halo" aria-hidden="true" />
            <ArtImage
              className="ld-app-laptop"
              src="/assets/obj-laptop-orange.png"
              alt="Prosto VPN на ноутбуке"
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
          <ArtImage className="ld-split-badge ld-split-badge-1" src="/assets/logo-t.png" speed={0.26} rotate={1.8} />
          <ArtImage className="ld-split-badge ld-split-badge-2" src="/assets/logo-vk.png" speed={0.18} rotate={-1.6} delay={100} />
        </div>
        <div className="wrap ld-split-in">
          <Reveal className="ld-split-head">
            <h2>
              Российские сервисы
              <br />
              работают как обычно
            </h2>
            <p>
              Встроенный обход держит банки, маркетплейсы и госуслуги на прямом подключении,
              пока остальной трафик идёт через VPN. Ничего не нужно включать вручную.
            </p>
          </Reveal>
          <div className="ld-split-cards">
            {BYPASS.map((c, i) => (
              <Reveal className="ld-split-card" key={c.title} delay={i * 70}>
                <h3>{c.title}</h3>
                <p>{c.text}</p>
              </Reveal>
            ))}
          </div>
          <Reveal className="ld-split-note">
            <span>
              Список сервисов обновляется автоматически — новые приложения попадают в
              исключения без обновления VPN.
            </span>
            <a href="#plans" className="btn btn-primary ld-split-note-btn">
              Подключить
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
              Один тариф.
              <br />
              Все возможности
            </h2>
            <p>Чем длиннее срок, тем ниже цена месяца. Отменить можно в любой момент.</p>
          </Reveal>

          {/*
          Пробный период стоит перед платными карточками и выглядит иначе:
          его не покупают, его получают регистрацией. Одинаковая карточка с
          кнопкой «Выбрать» вела бы в платёжную форму на ноль рублей.
          */}
          {trial && (
            <Reveal className="ld-trial">
              <div className="ld-trial-body">
                <span className="ld-trial-tag">Бесплатно</span>
                <h3>
                  {trial.title}: {trial.term} и {trial.traffic}
                </h3>
                <p>
                  {trial.note ||
                    "Заведите аккаунт — доступ откроется сразу, платёжная карта не нужна."}
                </p>
              </div>
              <Link to="/login" className="btn btn-primary ld-trial-btn">
                Попробовать бесплатно
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
                  <span className="ld-plan-per">/ мес</span>
                </div>
                <p className="ld-plan-note">{p.note}</p>
                <ul className="ld-plan-limits">
                  {p.limits.map((limit) => (
                    <li key={limit}>{limit}</li>
                  ))}
                </ul>
                <Link
                  to="/login"
                  className={`btn ld-plan-btn ${p.featured ? "btn-primary" : "btn-outline"}`}
                >
                  Выбрать
                </Link>
              </Reveal>
            ))}
          </div>

          <Reveal className="ld-plans-fine" delay={120}>
            Устройства считаются по одновременным входам: вход с лишнего отключает самое
            старое, а не запрещает войти. Когда включённый трафик заканчивается, доступ
            закрывается до продления — приложение предупреждает заранее, когда остаётся
            меньше 5 ГБ.
          </Reveal>
        </div>
      </section>

      {/* Щит */}
      <section id="security" className="ld-shield">
        <div className="wrap ld-shield-grid">
          <Reveal className="ld-shield-body">
            <h2>
              Щит
              <br />
              Prosto
            </h2>
            <div className="ld-shield-list">
              {SHIELD.map((item) => (
                <div key={item.title}>
                  <h3>{item.title}</h3>
                  <p>{item.text}</p>
                </div>
              ))}
            </div>
            <Link to="/faq" className="btn ld-shield-btn">
              Подробнее
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
            <h3>Одна подписка — все устройства</h3>
            <p>iPhone, Android, Mac и Windows. Одновременных подключений — {devicesLabel}.</p>
          </Reveal>
          <Reveal className="ld-devices-tags" delay={120}>
            {["iOS", "Android", "macOS", "Windows"].map((t) => (
              <span key={t}>{t}</span>
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
              Прозрачно
              <br />
              во всём
            </h2>
            <p>Всё, что стоит прочитать до подключения</p>
          </Reveal>
          <div className="ld-docs-grid">
            {DOCS.map((d, i) => (
              <Reveal as="div" key={d.title} delay={i * 70}>
                <Link to={d.to} className="ld-docs-card">
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

      <SiteFooter />
    </div>
  );
}
