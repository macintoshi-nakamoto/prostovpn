import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { financeApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { money } from "../../lib/format";
import { Button, Card, ErrorBox, Loading, PageHead } from "../../ui";
import { MonthGrid } from "./MonthGrid";
import { RevenueSummary } from "./RevenueSummary";
import { DayDetails } from "./DayDetails";
import "./calendar.css";

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

export function CalendarPage() {
  const today = useMemo(() => new Date(), []);
  const [cursor, setCursor] = useState({ year: today.getFullYear(), month: today.getMonth() + 1 });
  const [selected, setSelected] = useState(null);

  const calendar = useAsync(
    () => financeApi.calendar(cursor.year, cursor.month),
    [cursor.year, cursor.month],
  );
  const revenue = useAsync(() => financeApi.revenue(), []);

  const shift = (delta) => {
    setSelected(null);
    setCursor(({ year, month }) => {
      const next = month + delta;
      if (next < 1) return { year: year - 1, month: 12 };
      if (next > 12) return { year: year + 1, month: 1 };
      return { year, month: next };
    });
  };

  const isCurrentMonth =
    cursor.year === today.getFullYear() && cursor.month === today.getMonth() + 1;

  const data = calendar.data;
  const selectedDay = data?.days.find((d) => d.date === selected) || null;
  const currency = data?.currency || "RUB";

  return (
    <div className="gd-root">
      <PageHead title="Календарь прибыли" sub="Полученное и ожидаемое по дням">
        <div className="cal-nav">
          <Button size="sm" onClick={() => shift(-1)} aria-label="Предыдущий месяц">
            <ChevronLeft size={16} />
          </Button>
          <div className="cal-month">
            {MONTHS[cursor.month - 1]} {cursor.year}
          </div>
          <Button size="sm" onClick={() => shift(1)} aria-label="Следующий месяц">
            <ChevronRight size={16} />
          </Button>
        </div>
        {!isCurrentMonth && (
          <Button
            size="sm"
            onClick={() => {
              setSelected(null);
              setCursor({ year: today.getFullYear(), month: today.getMonth() + 1 });
            }}
          >
            Сегодня
          </Button>
        )}
      </PageHead>

      <ErrorBox error={calendar.error} onRetry={calendar.reload} />

      <div className="cal-layout">
        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
          <Card pad>
            <div className="cal-totals">
              <div>
                <div className="cal-total-v gd-num">{money(data?.actualTotal ?? 0, currency)}</div>
                <div className="cal-total-l">Получено за месяц</div>
              </div>
              <div>
                <div className="cal-total-v gd-num" style={{ color: "var(--gd-gold)" }}>
                  {money(data?.expectedTotal ?? 0, currency)}
                </div>
                <div className="cal-total-l">Ожидается по продлениям</div>
              </div>
            </div>

            {calendar.loading && !data ? (
              <Loading text="Считаем месяц" />
            ) : (
              <MonthGrid
                data={data}
                currency={currency}
                selected={selected}
                onSelect={(day) => setSelected((cur) => (cur === day.date ? null : day.date))}
              />
            )}
          </Card>

          {selectedDay && (
            <DayDetails day={selectedDay} currency={currency} onClose={() => setSelected(null)} />
          )}
        </div>

        <RevenueSummary summary={revenue.data} loading={revenue.loading} />
      </div>
    </div>
  );
}
