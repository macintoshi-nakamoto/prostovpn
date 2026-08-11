import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { api } from "../lib/api";
import { moneyFromKopecks } from "../lib/format";
import "./landing.css";

const FEATURES = [
  { icon: "ic-arc.png", title: "До 1 Гбит/с", text: "Скорость не режется даже в час пик", plain: true },
  { icon: "ic-territory-2.png", title: "60+ стран", text: "Более 900 серверов на пяти континентах" },
  { icon: "ic-devices-2.png", title: "5 устройств", text: "Одна подписка на всю семью" },
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

/**
 * Тарифы для карточек.
 *
 * Берём настоящие из панели: там их и заводят, и правят цены. Вёрстка от
 * макета остаётся — три карточки, средняя выделена, — а содержимое живое.
 * Цену показываем за месяц, как в макете: длинный тариф так выигрышнее
 * читается, а полная сумма уходит в подпись под ней.
 *
 * Выделяем самый выгодный по цене месяца, а не средний по порядку: если
 * тарифы переставят в панели, выделение не должно уехать на случайный.
 */
function toCards(list) {
  const byDuration = [...list].sort((a, b) => a.duration_days - b.duration_days).slice(0, 3);

  const cards = byDuration.map((plan) => {
    const months = Math.max(1, Math.round(plan.duration_days / 30));
    const perMonth = Math.round(plan.price_kopecks / months);
    const full = moneyFromKopecks(plan.price_kopecks, plan.currency);
    return {
      code: plan.code,
      term: plan.title,
      perMonth: moneyFromKopecks(perMonth, plan.currency),
      perMonthValue: perMonth,
      note: plan.tagline || `${full} за ${plan.duration_days} дней`,
      featured: false,
    };
  });

  if (cards.length > 1) {
    /*
    Выделяем самый длинный срок — ровно то, о чём говорит заголовок секции:
    «чем длиннее срок, тем ниже цена месяца». Брать самый дешёвый месяц
    нельзя: дешевле всех обычно начальный тариф, и он дешёвый не из-за
    срока, а из-за лимитов, — выделять его как выгодный было бы неправдой.
    */
    const longest = cards[cards.length - 1];
    longest.featured = true;

    // Бейдж со скидкой — только если месяц действительно дешевле, чем на
    // самом коротком тарифе. Нет выгоды — нет и обещания.
    const shortest = cards[0];
    const off = Math.round((1 - longest.perMonthValue / shortest.perMonthValue) * 100);
    if (off >= 5) longest.badge = `−${off}%`;
  }

  return cards;
}

const FALLBACK_PLANS = [
  { term: "1 месяц", perMonth: "399 ₽", note: "Попробовать без обязательств", featured: false },
  { term: "12 месяцев", perMonth: "169 ₽", note: "2 028 ₽ в год", featured: true, badge: "−58%" },
  { term: "3 года", perMonth: "119 ₽", note: "4 284 ₽ за весь срок", featured: false },
];

export function Landing() {
  const [plans, setPlans] = useState(FALLBACK_PLANS);

  useEffect(() => {
    let alive = true;
    api
      .plans()
      .then((list) => {
        // Панель недоступна или тарифов нет — остаются значения из макета:
        // пустая секция цен хуже, чем ориентировочная.
        if (!alive || !Array.isArray(list) || list.length === 0) return;
        setPlans(toCards(list));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="ld">
      <SiteHeader />

      {/* Герой */}
      <section id="top" className="ld-hero">
        <div className="ld-hero-glow" aria-hidden="true" />
        <div className="wrap ld-hero-in">
          <Reveal className="ld-hero-body">
            <h1>
              Интернет
              <br />
              без границ
            </h1>
            <p>
              Подключение в одно нажатие, 60+ стран и скорость до 1 Гбит/с. Без логов, без
              лимитов трафика и без настроек.
            </p>
            <div className="ld-hero-cta">
              <a href="#plans" className="btn ld-hero-primary">
                Начать использовать
              </a>
              <a href="#app" className="btn ld-hero-ghost">
                Как это работает
              </a>
            </div>
            <span className="ld-hero-plats">iOS · Android · macOS · Windows</span>
          </Reveal>
        </div>
      </section>

      {/* Четыре преимущества */}
      <section className="ld-features">
        <div className="wrap ld-features-grid">
          {FEATURES.map((f, i) => (
            <Reveal className="ld-feature" key={f.title} delay={i * 80}>
              <img
                src={`/assets/${f.icon}`}
                alt=""
                className={f.plain ? "" : "ld-feature-shadow"}
              />
              <h3>{f.title}</h3>
              <p>{f.text}</p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Ноль записей */}
      <section id="speed" className="ld-zero">
        <img className="ld-zero-obj ld-zero-left float" src="/assets/obj-ruble-lock.png" alt="" aria-hidden="true" />
        <img className="ld-zero-obj ld-zero-right float" src="/assets/obj-platforms.png" alt="" aria-hidden="true" />
        <Reveal className="ld-zero-in">
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
                <img src="/assets/ic-appstore.png" alt="" />
                App Store
              </Link>
              <Link to="/login" className="btn btn-dark ld-store">
                <img src="/assets/ic-googleplay.png" alt="" />
                Google Play
              </Link>
            </div>
          </Reveal>
          <div className="ld-app-art">
            <div className="ld-app-halo" aria-hidden="true" />
            <img src="/assets/obj-laptop-orange.png" alt="Prosto VPN на ноутбуке" />
          </div>
        </div>
      </section>

      {/* Российские сервисы */}
      <section id="split" className="ld-split">
        <div className="ld-split-deco" aria-hidden="true">
          <img className="ld-split-ribbon" src="/assets/ribbon-diagonal.png" alt="" />
          <img className="ld-split-badge ld-split-badge-1 float" src="/assets/logo-t.png" alt="" />
          <img className="ld-split-badge ld-split-badge-2 float" src="/assets/logo-vk.png" alt="" />
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
        <img className="ld-plans-ribbon" src="/assets/ribbon-spiral.png" alt="" aria-hidden="true" />
        <div className="wrap ld-plans-in">
          <Reveal className="ld-plans-head">
            <h2>
              Один тариф.
              <br />
              Все возможности
            </h2>
            <p>Чем длиннее срок, тем ниже цена месяца. Отменить можно в любой момент.</p>
          </Reveal>
          <div className="ld-plans-grid">
            {plans.map((p, i) => (
              <Reveal
                className={`ld-plan${p.featured ? " ld-plan-featured" : ""}`}
                key={p.term}
                delay={i * 90}
              >
                {p.badge && <span className="ld-plan-badge">{p.badge}</span>}
                <span className="ld-plan-term">{p.term}</span>
                <div className="ld-plan-price">
                  <span className="ld-plan-sum">{p.perMonth}</span>
                  <span className="ld-plan-per">/ мес</span>
                </div>
                <p className="ld-plan-note">{p.note}</p>
                <Link
                  to="/login"
                  className={`btn ld-plan-btn ${p.featured ? "btn-primary" : "btn-outline"}`}
                >
                  Выбрать
                </Link>
              </Reveal>
            ))}
          </div>
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
            <img className="float" src="/assets/obj-case-2.png" alt="" />
          </div>
        </div>
      </section>

      {/* Одна подписка — все устройства */}
      <section className="ld-devices">
        <img className="ld-devices-phone" src="/assets/obj-iphone-side.png" alt="" aria-hidden="true" />
        <div className="wrap ld-devices-in">
          <Reveal className="ld-devices-body">
            <h3>Одна подписка — все устройства</h3>
            <p>iPhone, Android, Mac и Windows. До пяти подключений одновременно.</p>
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
        <img className="ld-docs-ribbon" src="/assets/ribbon-wave.png" alt="" aria-hidden="true" />
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
