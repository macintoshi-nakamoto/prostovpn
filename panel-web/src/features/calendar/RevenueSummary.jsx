import { money } from "../../lib/format";
import { Card, Loading, Trend } from "../../ui";

/** Сводка сбоку: день, неделя, месяц, год. */
export function RevenueSummary({ summary, loading }) {
  if (loading && !summary) {
    return (
      <Card pad>
        <Loading text="Считаем" />
      </Card>
    );
  }
  if (!summary) return null;

  const currency = summary.currency;
  const dayTrend = growth(summary.day, summary.prevDay);
  const weekTrend = growth(summary.week, summary.prevWeek);

  return (
    <div className="cal-side">
      {/* Год — главная цифра, поэтому золотом. */}
      <Card className="gd-gold" style={{ padding: "26px 26px" }}>
        <div className="v gd-num">{money(summary.year, currency)}</div>
        <div className="l" style={{ marginTop: 8 }}>
          Прибыль за год
        </div>
      </Card>

      <Card pad>
        <Row label="За день" value={money(summary.day, currency)} trend={dayTrend} />
        <Row label="За неделю" value={money(summary.week, currency)} trend={weekTrend} />
        <Row label="За месяц" value={money(summary.month, currency)} />
      </Card>

      <div className="gd-cream">
        <div className="cv">{money(summary.expectedMonth, currency)}</div>
        <div className="cl">Ожидается в этом месяце по продлениям</div>
      </div>
    </div>
  );
}

function Row({ label, value, trend }) {
  return (
    <div className="cal-sum-row">
      <div>
        <div className="cal-sum-v gd-num">{value}</div>
        <div className="cal-sum-l">{label}</div>
      </div>
      {trend != null && (
        <div style={{ marginLeft: "auto" }}>
          <Trend pct={trend} />
        </div>
      )}
    </div>
  );
}

/**
 * Прирост к прошлому периоду.
 *
 * От нуля процент не считается — вернём null, иначе на первом же дне с
 * оплатой в интерфейсе появляется бесконечность.
 */
function growth(current, previous) {
  const now = Number(current || 0);
  const before = Number(previous || 0);
  if (before <= 0) return null;
  return ((now - before) / before) * 100;
}
