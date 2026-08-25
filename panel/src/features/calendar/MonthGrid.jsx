import { moneyShort } from "../../lib/format";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export function MonthGrid({ data, currency, selected, onSelect }) {
  if (!data) return null;

  const leading = data.days.length ? data.days[0].weekday : 0;
  const cells = [...Array(leading).fill(null), ...data.days];

  const max = Math.max(
    ...data.days.map((d) => Number(d.actual) + Number(d.expected)),
    1,
  );

  return (
    <div className="cal-grid-wrap">
      <div className="cal-weekdays">
        {WEEKDAYS.map((label) => (
          <div key={label} className="cal-weekday">
            {label}
          </div>
        ))}
      </div>

      <div className="cal-grid">
        {cells.map((day, index) => {
          if (!day) return <div key={`pad-${index}`} className="cal-cell empty" />;

          const actual = Number(day.actual);
          const expected = Number(day.expected);
          const total = actual + expected;
          const share = total / max;

          const classes = [
            "cal-cell",
            day.isToday ? "today" : "",
            selected === day.date ? "selected" : "",
            total > 0 ? "has-money" : "",
            day.isPast ? "past" : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <button key={day.date} className={classes} onClick={() => onSelect(day)} type="button">
              {total > 0 && (
                <span
                  className="cal-fill"
                  style={{ opacity: 0.08 + share * 0.24 }}
                  aria-hidden="true"
                />
              )}

              <span className="cal-daynum">{Number(day.date.slice(-2))}</span>

              <span className="cal-amounts">
                {actual > 0 && <span className="cal-actual gd-num">{moneyShort(actual, currency)}</span>}
                {expected > 0 && (
                  <span className="cal-expected gd-num">+{moneyShort(expected, currency)}</span>
                )}
              </span>

              {(day.payments.length > 0 || day.renewals.length > 0) && (
                <span className="cal-count">
                  {day.payments.length > 0 && <i className="cal-pip paid" />}
                  {day.renewals.length > 0 && <i className="cal-pip due" />}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="cal-legend">
        <span>
          <i className="cal-pip paid" /> оплачено
        </span>
        <span>
          <i className="cal-pip due" /> ожидается продление
        </span>
      </div>
    </div>
  );
}
