import { X } from "lucide-react";
import { Link } from "react-router-dom";
import { date, money, plural } from "../../lib/format";
import { Card, Empty } from "../../ui";

/** Кто заплатил и кто должен продлиться в выбранный день. */
export function DayDetails({ day, currency, onClose }) {
  const hasAnything = day.payments.length > 0 || day.renewals.length > 0;

  return (
    <Card pad>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{date(day.date)}</div>
          <div className="gd-sub" style={{ marginTop: 4 }}>
            Получено {money(day.actual, currency)}
            {Number(day.expected) > 0 && ` · ожидается ${money(day.expected, currency)}`}
          </div>
        </div>
        <button className="gd-x" onClick={onClose} aria-label="Закрыть">
          <X size={16} />
        </button>
      </div>

      {!hasAnything && <Empty>В этот день движения денег нет</Empty>}

      {day.payments.length > 0 && (
        <Group
          title={`Оплатили — ${day.payments.length} ${plural(day.payments.length, "человек", "человека", "человек")}`}
          rows={day.payments}
          currency={currency}
          color="var(--gd-pos)"
        />
      )}

      {day.renewals.length > 0 && (
        <Group
          title="Ожидаются продления"
          rows={day.renewals}
          currency={currency}
          color="var(--gd-gold)"
          expected
        />
      )}
    </Card>
  );
}

function Group({ title, rows, currency, color, expected }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div className="gd-sec-title" style={{ marginBottom: 4 }}>
        {title}
      </div>
      <div className="gd-rows">
        {rows.map((row, index) => (
          <div key={`${row.userId}-${index}`} className="gd-r">
            <span className="gd-dot" style={{ background: color }} />
            <div style={{ minWidth: 0 }}>
              {/* Из календаря сразу к человеку: следующий вопрос всегда «кто это». */}
              {row.userId ? (
                <Link
                  to={`/users/${row.userId}`}
                  style={{ fontWeight: 600, color: "inherit", textDecoration: "none" }}
                >
                  {row.name || row.login}
                </Link>
              ) : (
                <span style={{ fontWeight: 600 }}>Без клиента</span>
              )}
              <div className="gd-cellsub gd-mono">
                {row.publicId || "—"}
                {expected && row.plan ? ` · ${row.plan}` : ""}
                {!expected && row.method ? ` · ${row.method}` : ""}
              </div>
            </div>
            <div className="r amt" style={{ color: expected ? color : undefined }}>
              {expected ? "+" : ""}
              {money(row.amount, currency)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
