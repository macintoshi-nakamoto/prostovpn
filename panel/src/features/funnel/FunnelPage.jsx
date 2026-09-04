import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Clock, Snowflake, UserX } from "lucide-react";
import { financeApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { ago, dateTime, num } from "../../lib/format";
import { useFreshness } from "../../layout/AdminLayout";
import { Card, Chip, ErrorBox, Loading, PageHead, Seg, Tile } from "../../ui";

/**
 * Воронка: регистрация → доступ → подключение → оплата.
 *
 * Отвечает на один вопрос: где люди отваливаются. Поэтому этапы стоят в
 * ряд с процентом от предыдущего — а не от общего числа, — и следом идёт
 * список тех, кто зарегистрировался, но так и не подключился: с ними
 * поддержка может связаться сегодня.
 */

const PERIODS = [
  { id: 7, label: "7 дней" },
  { id: 30, label: "30 дней" },
  { id: 90, label: "90 дней" },
  { id: 0, label: "Всё время" },
];

const SOURCE_LABEL = {
  referral: "приглашение",
  telegram: "Telegram",
  site: "сайт",
  app: "приложение",
  admin: "вручную",
};

function pct(value, base) {
  if (!base) return "—";
  return `${Math.round((value / base) * 100)}%`;
}

export function FunnelPage() {
  const [days, setDays] = useState(30);
  const { data, loading, error, reload } = useAsync(() => financeApi.funnel(days), [days]);
  useFreshness(data, error);

  if (loading && !data) return <Loading text="Считаем воронку" />;
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  const stages = data.stages;
  const total = stages[0]?.count || 0;
  // Самое узкое место — этап с наименьшей долей от предыдущего (кроме
  // повторных платежей: их мало по природе).
  const weakest = stages
    .slice(1, 4)
    .reduce((acc, s) => (acc == null || s.pctPrev < acc.pctPrev ? s : acc), null);

  return (
    <div className="gd-root">
      <PageHead title="Воронка" sub="От регистрации до оплаты: где люди отваливаются">
        <Seg options={PERIODS} value={days} onChange={setDays} gold />
      </PageHead>

      <Card pad style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {num(total)} {plural(total, "регистрация", "регистрации", "регистраций")}
            {days ? ` за ${days} ${plural(days, "день", "дня", "дней")}` : " за всё время"}
          </div>
          {weakest && total > 0 && (
            <div className="gd-sub">
              Узкое место — «{weakest.label.toLowerCase()}»: доходит {weakest.pctPrev}% с предыдущего этапа
            </div>
          )}
        </div>

        <div className="fn-stages">
          {stages.map((stage, i) => (
            <div key={stage.key} className="fn-stage">
              {i > 0 && (
                <div className="fn-arrow" title="доля от предыдущего этапа">
                  <ArrowRight size={14} />
                  <span>{stage.pctPrev}%</span>
                </div>
              )}
              <div className="fn-stage-body">
                <div className="fn-stage-n gd-num">{num(stage.count)}</div>
                <div className="fn-stage-l">{stage.label}</div>
                <div className="fn-bar">
                  <span style={{ width: `${total ? Math.max((stage.count / total) * 100, stage.count ? 2 : 0) : 0}%` }} />
                </div>
                <div className="fn-stage-s">{stage.pctTotal}% от всех</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))", marginBottom: 16 }}>
        <Tile
          label="До первого подключения"
          value={
            <IconValue icon={<Clock size={17} />}>
              {data.medianHoursToConnect == null ? "—" : hours(data.medianHoursToConnect)}
            </IconValue>
          }
          sub="медиана среди подключившихся"
        />
        <Tile
          label="До первой оплаты"
          value={
            <IconValue icon={<Clock size={17} />}>
              {data.medianDaysToPay == null ? "—" : `${data.medianDaysToPay} ${plural(Math.round(data.medianDaysToPay), "день", "дня", "дней")}`}
            </IconValue>
          }
          sub="медиана среди оплативших"
        />
        <Tile
          label="Остыли"
          value={<IconValue icon={<Snowflake size={17} />}>{num(data.cooledCount)}</IconValue>}
          sub="подключались, не платили, доступ кончился"
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 16, marginBottom: 16 }} className="fn-two">
        <Card pad>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>По источникам</div>
          <div className="gd-sub" style={{ marginBottom: 12 }}>
            Откуда пришли и до чего дошли
          </div>
          <MiniTable
            head={["Источник", "Рег.", "Доступ", "Подкл.", "Оплата"]}
            rows={data.sources.map((s) => [
              s.label,
              num(s.registered),
              cell(s.setup, s.registered),
              cell(s.connected, s.registered),
              cell(s.paid, s.registered),
            ])}
            empty="Пока никого"
          />
        </Card>

        <Card pad>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>По неделям регистрации</div>
          <div className="gd-sub" style={{ marginBottom: 12 }}>
            Свежие когорты ещё не успели дойти до оплаты — сравнивайте одинаковый возраст
          </div>
          <MiniTable
            head={["Неделя", "Рег.", "Доступ", "Подкл.", "Оплата"]}
            rows={[...data.cohorts].reverse().map((c) => [
              c.label,
              num(c.registered),
              cell(c.setup, c.registered),
              cell(c.connected, c.registered),
              cell(c.paid, c.registered),
            ])}
            empty="Пока никого"
          />
        </Card>
      </div>

      <Card pad>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
          <span className="gd-badge">
            <UserX size={19} />
          </span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              Зарегистрировались, но не подключились · {num(data.stuckCount)}
            </div>
            <div className="gd-sub" style={{ marginTop: 2 }}>
              Больше суток без единого подключения. С этими людьми стоит связаться: обычно они
              застряли на установке.
            </div>
          </div>
        </div>
        {data.stuck.length === 0 ? (
          <div className="gd-sub" style={{ marginTop: 12 }}>
            Таких нет — все, кто зарегистрировался, подключились.
          </div>
        ) : (
          <div className="gd-rows" style={{ marginTop: 12 }}>
            {data.stuck.map((u) => (
              <Link key={u.id} to={`/users/${u.id}`} className="gd-r" style={{ textDecoration: "none", color: "inherit" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {u.telegramUsername ? `@${u.telegramUsername}` : u.name || u.login}
                    <span className="gd-chip">{SOURCE_LABEL[u.source] || u.source}</span>
                    {u.hasSetup ? (
                      <Chip color="var(--gd-warn)">есть ключ, не подключался</Chip>
                    ) : (
                      <Chip color="var(--gd-faint)">не дошёл до ключа</Chip>
                    )}
                    {!u.accessActive && <Chip color="var(--gd-faint)">доступ кончился</Chip>}
                  </div>
                  <div className="gd-cellsub gd-mono">
                    {u.login} · {u.publicId} · регистрация {dateTime(u.createdAt)}
                  </div>
                </div>
                <div className="r" style={{ color: "var(--gd-dim)", fontSize: 13 }}>
                  {ago(u.createdAt)}
                </div>
              </Link>
            ))}
            {data.stuckCount > data.stuck.length && (
              <div className="gd-sub" style={{ paddingTop: 10 }}>
                Показаны последние {data.stuck.length} из {num(data.stuckCount)}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function IconValue({ icon, children }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
      <span style={{ color: "var(--gd-gold)", display: "inline-flex" }}>{icon}</span>
      {children}
    </span>
  );
}

function cell(value, base) {
  return (
    <span>
      <span className="gd-num">{num(value)}</span>
      <span style={{ color: "var(--gd-faint)", marginLeft: 6, fontSize: 12 }}>{pct(value, base)}</span>
    </span>
  );
}

function MiniTable({ head, rows, empty }) {
  if (!rows.length) return <div className="gd-sub">{empty}</div>;
  return (
    <div className="gd-table-wrap">
      <table className="gd-table fn-table">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={h} className={i > 0 ? "num" : undefined}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ cursor: "default" }}>
              {r.map((c, j) => (
                <td key={j} className={j > 0 ? "num" : undefined}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function hours(value) {
  if (value < 1) return `${Math.max(1, Math.round(value * 60))} мин`;
  if (value < 48) return `${Math.round(value)} ч`;
  return `${Math.round(value / 24)} ${plural(Math.round(value / 24), "день", "дня", "дней")}`;
}

function plural(count, one, few, many) {
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
}
