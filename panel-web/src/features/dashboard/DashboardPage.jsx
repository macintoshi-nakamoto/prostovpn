import { Link } from "react-router-dom";
import { Activity, Server, Users, Wallet } from "lucide-react";
import { financeApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { bytes, money, moneyShort, num } from "../../lib/format";
import { Bars, Card, ErrorBox, Loading, PageHead, Spark, Tile, Trend } from "../../ui";

export function DashboardPage() {
  const { data, loading, error, reload } = useAsync(() => financeApi.dashboard(), []);

  if (loading && !data) return <Loading text="Собираем сводку" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  const daily = data.daily.map((p) => Number(p.value));
  const monthly = data.monthly.map((p) => ({ label: p.label, value: Number(p.value) }));
  const currency = data.currency;

  return (
    <div className="gd-root">
      <PageHead title="Сводка" sub="Деньги, клиенты и серверы за один взгляд" />

      <div
        className="gd-hero-wrap"
        style={{ display: "grid", gridTemplateColumns: "minmax(0, 0.9fr) minmax(0, 1.1fr)", gap: 16, marginBottom: 16 }}
      >
        <Card className="gd-gold" style={{ padding: "26px 28px", display: "flex", flexDirection: "column" }}>
          <div className="v gd-num">{money(data.revenueMonth, currency)}</div>
          <div className="l" style={{ marginTop: 8 }}>
            Выручка за месяц
          </div>
          <div style={{ marginTop: "auto", paddingTop: 20, display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700 }} className="gd-num">
                {money(data.revenueDay, currency)}
              </div>
              <div className="l" style={{ fontSize: 12.5 }}>
                Сегодня
              </div>
            </div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700 }} className="gd-num">
                {money(data.revenueYear, currency)}
              </div>
              <div className="l" style={{ fontSize: 12.5 }}>
                За год
              </div>
            </div>
          </div>
        </Card>

        <Card pad>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
            <span className="gd-badge">
              <Wallet size={19} />
            </span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Поступления за 30 дней</div>
              <div className="gd-sub" style={{ marginTop: 2 }}>
                {money(daily.reduce((a, b) => a + b, 0), currency)} суммарно
              </div>
            </div>
            <div style={{ marginLeft: "auto" }}>
              <Trend pct={trendOf(daily)} />
            </div>
          </div>
          <div style={{ marginTop: 14 }}>
            <Spark data={daily} height={92} />
          </div>
        </Card>
      </div>

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: 16 }}>
        <StatTile icon={<Users size={17} />} to="/users" label="Клиентов" value={num(data.usersTotal)} sub={`${data.usersActive} с доступом`} />
        <StatTile icon={<Activity size={17} />} to="/users" label="Сейчас онлайн" value={num(data.sessionsOnline)} sub={`${data.usersBlocked} заблокировано`} />
        <StatTile icon={<Server size={17} />} to="/servers" label="Серверов" value={num(data.serversTotal)} sub={`${data.serversActive} включено`} />
        <StatTile icon={<Wallet size={17} />} to="/keys" label="Трафик клиентов" value={bytes(data.trafficUsedBytes)} sub="за всё время" />
      </div>

      <Card pad>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Выручка по месяцам</div>
        <div className="gd-sub" style={{ marginBottom: 16 }}>
          Последние 12 месяцев
        </div>
        <Bars data={monthly} height={120} />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, fontSize: 11, color: "var(--gd-faint)" }}>
          {monthly.map((m, i) =>
            // Подписываем каждый второй месяц: иначе на узком экране каша.
            i % 2 === 0 ? <span key={m.label}>{m.label.slice(5)}</span> : <span key={m.label} />,
          )}
        </div>
        <div style={{ marginTop: 12, fontSize: 12.5, color: "var(--gd-dim)" }}>
          Лучший месяц: {moneyShort(Math.max(...monthly.map((m) => m.value), 0), currency)}
        </div>
      </Card>
    </div>
  );
}

function StatTile({ icon, to, label, value, sub }) {
  return (
    <Link to={to} style={{ textDecoration: "none", color: "inherit", minWidth: 0 }}>
      <Tile
        label={label}
        value={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
            <span style={{ color: "var(--gd-gold)", display: "inline-flex" }}>{icon}</span>
            {value}
          </span>
        }
        sub={sub}
      />
    </Link>
  );
}

/** Половина периода против второй — грубо, зато честно и без сглаживаний. */
function trendOf(values) {
  if (values.length < 4) return null;
  const mid = Math.floor(values.length / 2);
  const first = values.slice(0, mid).reduce((a, b) => a + b, 0);
  const second = values.slice(mid).reduce((a, b) => a + b, 0);
  if (first <= 0) return null;
  return ((second - first) / first) * 100;
}
