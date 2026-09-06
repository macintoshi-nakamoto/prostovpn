import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { api } from "../lib/api";
import { NEWS_TELEGRAM, SUPPORT_CHAT } from "../lib/contacts.js";
import { useI18n } from "../lib/i18n/index.jsx";
import "./blocks.css";

/**
 * Карта блокировок — prostovpn.cc/blocks.
 *
 * Публичная сводка телеметрии: у какого оператора какой способ подключения
 * работает прямо сейчас. Данные — /api/v1/blocks (services/connectivity.py):
 * только суммы по оператору и протоколу, без адресов и устройств, кэш на
 * минуту. Страницу увидят люди, которым сейчас не подключается, — поэтому
 * главное сверху, крупно и словами, а цифры и графики ниже.
 */

const REFRESH_MS = 60_000;
const PROTOCOLS = ["awg", "vless", "hy2"];

function clock(iso, lang) {
  if (!iso) return "";
  const date = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(lang === "ru" ? "ru-RU" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function num(value, lang) {
  return Number(value || 0).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB");
}

function pct(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value)}%`;
}

function StatusIcon({ status }) {
  if (status === "ok") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="8.5" fill="currentColor" />
        <path d="M6 10.4l2.6 2.6L14 7.6" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === "partial") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M10 2.5l8 14H2z" fill="currentColor" />
        <path d="M10 8v4.2M10 15h.01" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  if (status === "blocked") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="8.5" fill="currentColor" />
        <path d="M7 7l6 6M13 7l-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="3 3" />
    </svg>
  );
}

function KindIcon({ kind }) {
  if (kind === "wifi") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M2.5 9.2a14 14 0 0119 0M5.6 12.4a9.6 9.6 0 0112.8 0M8.7 15.6a5.2 5.2 0 016.6 0" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
        <circle cx="12" cy="19" r="1.6" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="14" width="3.2" height="6" rx="1" fill="currentColor" />
      <rect x="8.4" y="10.5" width="3.2" height="9.5" rx="1" fill="currentColor" />
      <rect x="13.8" y="7" width="3.2" height="13" rx="1" fill="currentColor" />
      <rect x="19.2" y="3.5" width="3.2" height="16.5" rx="1" fill="currentColor" opacity="0.45" />
    </svg>
  );
}

function StatusPill({ status, t }) {
  return (
    <span className={"bk-pill is-" + status}>
      <StatusIcon status={status} />
      {t("blocks.status." + status)}
    </span>
  );
}

function Trend({ trend, prev, t }) {
  if (prev === null || prev === undefined) return null;
  const arrow = trend === "up" ? "↑" : trend === "down" ? "↓" : "→";
  return (
    <span className={"bk-trend is-" + trend}>
      <span aria-hidden="true">{arrow}</span> {t("blocks.trend." + trend, { prev: pct(prev) })}
    </span>
  );
}

/**
 * Успешность по часам за сутки. Тонкая линия, заливка под ней, точки только
 * на часах, где были попытки; при наведении — какой час, сколько попыток и
 * доля успешных. Ось времени — три подписи, не больше.
 */
function Sparkline({ points, lang, t, id }) {
  const [hover, setHover] = useState(null);
  const ref = useRef(null);
  const width = 320;
  const height = 72;
  const padX = 4;
  const padTop = 6;
  const padBottom = 18;
  const innerH = height - padTop - padBottom;
  const step = (width - padX * 2) / Math.max(1, points.length - 1);

  const coords = points.map((p, i) => ({
    x: padX + i * step,
    y: p.ok_pct === null || p.ok_pct === undefined ? null : padTop + innerH * (1 - p.ok_pct / 100),
    p,
    i,
  }));
  const known = coords.filter((c) => c.y !== null);
  let line = "";
  let area = "";
  known.forEach((c, idx) => {
    line += (idx === 0 ? "M" : "L") + c.x.toFixed(1) + " " + c.y.toFixed(1) + " ";
  });
  if (known.length > 1) {
    const first = known[0];
    const last = known[known.length - 1];
    area = line + `L${last.x.toFixed(1)} ${padTop + innerH} L${first.x.toFixed(1)} ${padTop + innerH} Z`;
  }

  const onMove = (event) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const x = ((event.clientX - box.left) / box.width) * width;
    let best = null;
    for (const c of coords) {
      if (best === null || Math.abs(c.x - x) < Math.abs(coords[best].x - x)) best = c.i;
    }
    setHover(best);
  };

  const hovered = hover === null ? null : coords[hover];
  const hoursAgo = (i) => points.length - 1 - i;
  const label = (i) => (hoursAgo(i) === 0 ? t("blocks.sparkNow") : t("blocks.sparkAgo", { h: hoursAgo(i) }));

  return (
    <div className="bk-spark" onMouseLeave={() => setHover(null)}>
      <svg
        ref={ref}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-labelledby={id + "-title"}
        onMouseMove={onMove}
      >
        <title id={id + "-title"}>{t("blocks.sparkTitle")}</title>
        <line className="bk-spark-grid" x1={padX} x2={width - padX} y1={padTop} y2={padTop} />
        <line className="bk-spark-grid" x1={padX} x2={width - padX} y1={padTop + innerH / 2} y2={padTop + innerH / 2} />
        <line className="bk-spark-base" x1={padX} x2={width - padX} y1={padTop + innerH} y2={padTop + innerH} />
        {area ? <path className="bk-spark-area" d={area} /> : null}
        {line ? <path className="bk-spark-line" d={line} /> : null}
        {known.map((c) => (
          <circle
            key={c.i}
            className={"bk-spark-dot" + (hover === c.i ? " is-hot" : "")}
            cx={c.x}
            cy={c.y}
            r={hover === c.i ? 4.5 : 2.6}
          />
        ))}
        {hovered ? (
          <line className="bk-spark-cursor" x1={hovered.x} x2={hovered.x} y1={padTop} y2={padTop + innerH} />
        ) : null}
      </svg>
      <div className="bk-spark-axis" aria-hidden="true">
        <span>{t("blocks.sparkAgo", { h: 24 })}</span>
        <span>{t("blocks.sparkAgo", { h: 12 })}</span>
        <span>{t("blocks.sparkNow")}</span>
      </div>
      {hovered ? (
        <div className="bk-tip" style={{ left: `${(hovered.x / width) * 100}%` }}>
          <b>{label(hovered.i)}</b>
          <span>
            {hovered.p.attempts
              ? t("blocks.sparkPoint", { pct: pct(hovered.p.ok_pct), n: num(hovered.p.attempts, lang) })
              : t("blocks.sparkNone")}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function OperatorCard({ op, t, lang, nowHours, index }) {
  const shown = op.ok_pct_now ?? op.ok_pct_day;
  return (
    <Reveal as="article" className={"bk-card is-" + op.status} delay={Math.min(index, 6) * 50}>
      <header className="bk-card-head">
        <div className="bk-op">
          <span className={"bk-kind is-" + op.kind} title={t("blocks.kind." + op.kind)}>
            <KindIcon kind={op.kind} />
          </span>
          <div>
            <h3>{op.name}</h3>
            <span className="bk-kind-label">{t("blocks.kind." + op.kind)}</span>
          </div>
        </div>
        <StatusPill status={op.status} t={t} />
      </header>

      <div className="bk-hero-num">
        <strong>{pct(shown)}</strong>
        <div className="bk-hero-sub">
          <span>
            {op.basis === "now"
              ? t("blocks.basisNow", { h: nowHours })
              : t("blocks.basisDay")}
          </span>
          <Trend trend={op.trend} prev={op.ok_pct_prev} t={t} />
        </div>
      </div>

      <Sparkline points={op.hourly} lang={lang} t={t} id={"spark-" + index} />

      {op.protocols.length ? (
        <ul className="bk-protos">
          {op.protocols.map((p) => {
            const value = p.ok_pct_now ?? p.ok_pct_day;
            return (
              <li key={p.code} className={"bk-proto is-" + p.status}>
                <span className={"bk-dot is-" + p.code} aria-hidden="true" />
                <span className="bk-proto-name">{p.title}</span>
                <span className="bk-bar" aria-hidden="true">
                  <i className={"bk-bar-fill is-" + p.code} style={{ width: `${Math.max(2, value || 0)}%` }} />
                </span>
                <span className="bk-proto-val">
                  {pct(value)}
                  <StatusIcon status={p.status} />
                </span>
                <small className="bk-proto-n">
                  {t("blocks.attemptsShort", {
                    n: num(p.ok_pct_now === null || p.ok_pct_now === undefined ? p.attempts_day : p.attempts_now, lang),
                  })}
                </small>
              </li>
            );
          })}
        </ul>
      ) : null}

      <footer className="bk-card-foot">
        <span>{t("blocks.sample", { attempts: num(op.attempts_day, lang), devices: num(op.devices_day, lang) })}</span>
        {op.best_now ? (
          <span className="bk-best">
            {t("blocks.bestNow", { proto: (op.protocols.find((p) => p.code === op.best_now) || {}).title || op.best_now })}
          </span>
        ) : null}
      </footer>
    </Reveal>
  );
}

function DataTable({ data, t, lang }) {
  const cols = t("blocks.table");
  return (
    <div className="bk-table-wrap">
      <table className="bk-table">
        <thead>
          <tr>
            <th>{cols.operator}</th>
            <th>{cols.status}</th>
            <th>{cols.now}</th>
            <th>{cols.day}</th>
            {PROTOCOLS.map((code) => (
              <th key={code}>{t("blocks.proto." + code)}</th>
            ))}
            <th>{cols.attempts}</th>
            <th>{cols.devices}</th>
          </tr>
        </thead>
        <tbody>
          {data.operators.map((op) => {
            const by = Object.fromEntries(op.protocols.map((p) => [p.code, p]));
            return (
              <tr key={op.name} className={"is-" + op.status}>
                <td>
                  <span className="bk-table-op">
                    <KindIcon kind={op.kind} /> {op.name}
                  </span>
                </td>
                <td>
                  <StatusPill status={op.status} t={t} />
                </td>
                <td>{pct(op.ok_pct_now)}</td>
                <td>{pct(op.ok_pct_day)}</td>
                {PROTOCOLS.map((code) => (
                  <td key={code}>{by[code] ? pct(by[code].ok_pct_now ?? by[code].ok_pct_day) : "—"}</td>
                ))}
                <td>{num(op.attempts_day, lang)}</td>
                <td>{num(op.devices_day, lang)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Blocks() {
  const { t, lang } = useI18n();
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState("cards");

  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.hidden) return;
      api
        .blocks()
        .then((r) => {
          if (!alive) return;
          setData(r);
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

  // Заголовок и описание для поиска и превью ссылок: страница живёт в SPA,
  // а делиться ей будут чаще, чем любой другой.
  useEffect(() => {
    const prevTitle = document.title;
    const meta = document.querySelector('meta[name="description"]');
    const prevDesc = meta ? meta.getAttribute("content") : null;
    document.title = t("blocks.docTitle");
    if (meta) meta.setAttribute("content", t("blocks.docDesc"));
    return () => {
      document.title = prevTitle;
      if (meta && prevDesc !== null) meta.setAttribute("content", prevDesc);
    };
  }, [lang, t]);

  const summary = data?.summary;
  const trouble = useMemo(
    () => (data ? data.operators.filter((o) => o.status === "partial" || o.status === "blocked") : []),
    [data],
  );
  const blocked = trouble.filter((o) => o.status === "blocked");
  const tone = blocked.length ? "bad" : trouble.length ? "warn" : "ok";

  let headline = t("blocks.loading");
  let headStatus = null;
  if (failed && !data) headline = t("blocks.unreachable");
  else if (data && !data.operators.length) {
    headline = t("blocks.headEmpty");
    headStatus = "quiet";
  } else if (data && blocked.length) {
    headline = t("blocks.headBlocked", { names: blocked.map((o) => o.name).join(", ") });
    headStatus = "blocked";
  } else if (data && trouble.length) {
    headline = t("blocks.headPartial", { names: trouble.map((o) => o.name).join(", ") });
    headStatus = "partial";
  } else if (data) {
    headline = t("blocks.headOk");
    headStatus = "ok";
  }

  const updated = data ? clock(data.updated_at, lang) : "";
  const platforms = summary?.platforms || [];
  const onlyAndroid = platforms.length > 0 && platforms.every((p) => p === "android");

  return (
    <div className="bk">
      <SiteHeader />
      <section className={"bk-hero is-" + tone}>
        <div className="wrap">
          <Reveal className="bk-hero-in">
            <span className="bk-eyebrow">{t("blocks.eyebrow")}</span>
            <h1 className="bk-head">
              {headStatus ? (
                <span className={"bk-head-mark is-" + headStatus} aria-hidden="true">
                  <StatusIcon status={headStatus} />
                </span>
              ) : null}
              <span>{headline}</span>
            </h1>
            <p>{t("blocks.lead")}</p>
            {updated ? (
              <span className="bk-hero-meta">
                {t("blocks.updated", { time: updated })} · {t("blocks.refresh")} · {t("blocks.noAddresses")}
              </span>
            ) : null}
          </Reveal>
        </div>
      </section>

      <section className="bk-body">
        <div className="wrap bk-body-in">
          {summary ? (
            <Reveal className="bk-stats" delay={40}>
              <div className="bk-stat">
                <strong>{num(summary.operators, lang)}</strong>
                <span>{t("blocks.statOperators")}</span>
              </div>
              <div className="bk-stat">
                <strong>{num(summary.attempts_day, lang)}</strong>
                <span>{t("blocks.statAttempts")}</span>
              </div>
              <div className="bk-stat">
                <strong>{num(summary.devices_day, lang)}</strong>
                <span>{t("blocks.statDevices")}</span>
              </div>
              <div className="bk-stat">
                <strong>{pct(summary.ok_pct_now ?? summary.ok_pct_day)}</strong>
                <span>{summary.ok_pct_now !== null && summary.ok_pct_now !== undefined ? t("blocks.statOkNow") : t("blocks.statOkDay")}</span>
              </div>
            </Reveal>
          ) : null}

          {data && data.operators.length ? (
            <>
              <Reveal className="bk-toolbar" delay={60}>
                <div className="bk-legend" aria-label={t("blocks.legendTitle")}>
                  {PROTOCOLS.map((code) => (
                    <span key={code} className="bk-legend-item" title={t("blocks.protoHint." + code)}>
                      <span className={"bk-dot is-" + code} aria-hidden="true" />
                      <b>{t("blocks.proto." + code)}</b>
                      <small>{t("blocks.protoHint." + code)}</small>
                    </span>
                  ))}
                </div>
                <div className="bk-view" role="tablist" aria-label={t("blocks.viewLabel")}>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={view === "cards"}
                    className={view === "cards" ? "is-on" : ""}
                    onClick={() => setView("cards")}
                  >
                    {t("blocks.viewCards")}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={view === "table"}
                    className={view === "table" ? "is-on" : ""}
                    onClick={() => setView("table")}
                  >
                    {t("blocks.viewTable")}
                  </button>
                </div>
              </Reveal>

              {view === "cards" ? (
                <div className="bk-grid">
                  {data.operators.map((op, index) => (
                    <OperatorCard key={op.name} op={op} t={t} lang={lang} nowHours={data.now_hours} index={index} />
                  ))}
                </div>
              ) : (
                <Reveal className="bk-card bk-card-table">
                  <DataTable data={data} t={t} lang={lang} />
                </Reveal>
              )}
            </>
          ) : data ? (
            <Reveal className="bk-card bk-empty">
              <h2>{t("blocks.emptyTitle")}</h2>
              <p>{t("blocks.emptyText", { attempts: data.thresholds.operator_attempts, devices: data.thresholds.operator_devices })}</p>
            </Reveal>
          ) : (
            <div className="bk-card bk-empty">
              <p className="bk-quiet">{headline}</p>
            </div>
          )}

          {data && data.watching.length ? (
            <Reveal className="bk-watch" delay={80}>
              <h2>{t("blocks.watchingTitle")}</h2>
              <p>
                {t("blocks.watchingText", {
                  attempts: data.thresholds.operator_attempts,
                  devices: data.thresholds.operator_devices,
                })}
              </p>
              <ul>
                {data.watching.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </Reveal>
          ) : null}

          {data ? (
            <Reveal className="bk-card bk-events" delay={100}>
              <h2>{t("blocks.eventsTitle")}</h2>
              {data.events.length ? (
                <ul>
                  {data.events.map((e, i) => (
                    <li key={i} className={"is-" + e.kind}>
                      <span className={"bk-event-mark is-" + e.kind} aria-hidden="true">
                        {e.kind === "drop" ? "↓" : "↑"}
                      </span>
                      <span className="bk-event-what">
                        <b>{e.operator}</b> · {e.title}
                      </span>
                      <span className="bk-event-num">
                        {pct(e.from_pct)} → {pct(e.to_pct)}
                      </span>
                      <span className="bk-event-kind">{t("blocks.event." + e.kind)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="bk-quiet">{t("blocks.eventsEmpty")}</p>
              )}
            </Reveal>
          ) : null}

          <Reveal className="bk-card bk-how" delay={120}>
            <h2>{t("blocks.howTitle")}</h2>
            <ol>
              {t("blocks.howItems").map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ol>
            {onlyAndroid ? <p className="bk-coverage">{t("blocks.coverage")}</p> : null}
          </Reveal>

          <Reveal className="bk-cta" delay={140}>
            <div>
              <h2>{t("blocks.ctaTitle")}</h2>
              <p>{t("blocks.ctaText")}</p>
            </div>
            <div className="bk-cta-acts">
              <Link to="/#plans" className="btn btn-primary">
                {t("blocks.ctaConnect")}
              </Link>
              <a className="bk-cta-link" href={NEWS_TELEGRAM} target="_blank" rel="noreferrer">
                {t("blocks.ctaChannel")}
              </a>
              <Link to="/status" className="bk-cta-link">
                {t("blocks.ctaStatus")}
              </Link>
              <a className="bk-cta-link" href={SUPPORT_CHAT} target="_blank" rel="noreferrer">
                {t("blocks.ctaSupport")}
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
