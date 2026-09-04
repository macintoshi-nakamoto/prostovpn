import { useState } from "react";
import { RadioTower, Smartphone, UserX } from "lucide-react";
import { financeApi } from "../../lib/api";
import { useAsync, usePolling } from "../../lib/hooks";
import { ago, num } from "../../lib/format";
import { useFreshness } from "../../layout/AdminLayout";
import { Card, Chip, ErrorBox, Loading, PageHead, Seg, Tile } from "../../ui";

/**
 * Связь: отчёты приложений о попытках подключиться.
 *
 * Главная таблица — оператор × протокол: по ней видно, где режут
 * AmneziaWG и спасает ли Reality. Ниже — по типу сети, по узлам, по
 * версиям приложения, частые ошибки и последние неудачи по одной.
 */

const PERIODS = [
  { id: 1, label: "Сутки" },
  { id: 7, label: "7 дней" },
  { id: 30, label: "30 дней" },
  { id: 90, label: "90 дней" },
];

const PROTO = { awg: "AmneziaWG", vless: "Reality", hy2: "Hysteria2" };
const KIND = { wifi: "Wi-Fi", cellular: "Сотовая", ethernet: "Кабель", other: "Другая", unknown: "Не знаем", none: "Без сети" };
const PLATFORM = { android: "Android", windows: "Windows", macos: "macOS", ios: "iOS" };

function okColor(pct, attempts) {
  if (!attempts) return "var(--gd-faint)";
  if (pct >= 90) return "var(--gd-pos)";
  if (pct >= 60) return "var(--gd-warn)";
  return "var(--gd-neg)";
}

function ms(value) {
  if (value == null) return "—";
  if (value < 1000) return `${value} мс`;
  return `${(value / 1000).toFixed(1)} с`;
}

export function TelemetryPage() {
  const [days, setDays] = useState(7);
  const { data, loading, error, reload } = useAsync(() => financeApi.telemetry(days), [days]);
  usePolling(() => reload(true), 60000);
  useFreshness(data, error);

  if (loading && !data) return <Loading text="Собираем отчёты" />;
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  // Матрица оператор × протокол.
  const protocols = ["awg", "vless", "hy2"].filter((p) => data.protocols.some((x) => x.protocol === p));
  const operatorNames = [...new Set(data.operators.map((o) => o.operator))];
  const cellOf = (list, keyName, key, protocol) =>
    list.find((x) => x[keyName] === key && x.protocol === protocol);

  return (
    <div className="gd-root">
      <PageHead title="Связь" sub="Что реально подключается у людей: по операторам, сетям и узлам">
        <Seg options={PERIODS} value={days} onChange={setDays} gold />
      </PageHead>

      {data.reports === 0 ? (
        <Card pad style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
            <RadioTower size={20} style={{ color: "var(--gd-gold)", flex: "none", marginTop: 2 }} />
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Отчётов пока нет</div>
              <div style={{ fontSize: 13.5, color: "var(--gd-dim)", lineHeight: 1.55 }}>
                Их присылают приложения Windows с 1.0.34 и Android с 1.1.11 после каждой попытки
                подключиться. Как только люди обновятся, здесь появятся цифры.
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: 16 }}>
        <Tile
          label="Попыток"
          value={<IconValue icon={<RadioTower size={17} />}>{num(data.reports)}</IconValue>}
          sub={`${num(data.ok)} удачных · ${data.okPct}%`}
        />
        <Tile
          label="Людей с отчётами"
          value={<IconValue icon={<Smartphone size={17} />}>{num(data.usersReporting)}</IconValue>}
          sub="приложения новых версий"
        />
        <Tile
          label="Ни разу не подключились"
          value={<IconValue icon={<UserX size={17} />}>{num(data.usersNeverOk)}</IconValue>}
          sub="за период только неудачи"
        />
        <Tile
          label="Лучший протокол"
          value={best(data.protocols)}
          sub="по доле удачных попыток"
        />
      </div>

      <Card pad style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Оператор × протокол</div>
        <div className="gd-sub" style={{ marginBottom: 12 }}>
          Доля удачных попыток и медиана времени до подключения. Wi-Fi без оператора — отдельной строкой.
        </div>
        <Matrix
          rowsKey="operator"
          rows={operatorNames}
          cols={protocols}
          get={(op, p) => cellOf(data.operators, "operator", op, p)}
          rowLabel={(op) => op}
        />
      </Card>

      <div className="fn-two" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 16, marginBottom: 16 }}>
        <Card pad>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>По типу сети</div>
          <Matrix
            rows={[...new Set(data.kinds.map((k) => k.kind))]}
            cols={protocols}
            get={(k, p) => cellOf(data.kinds, "kind", k, p)}
            rowLabel={(k) => KIND[k] || k}
          />
        </Card>
        <Card pad>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>По узлам</div>
          <Matrix
            rows={[...new Set(data.servers.map((s) => s.server))]}
            cols={protocols}
            get={(srv, p) => cellOf(data.servers, "server", srv, p)}
            rowLabel={(srv) => srv}
          />
        </Card>
      </div>

      <div className="fn-two" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 16, marginBottom: 16 }}>
        <Card pad>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>По версиям приложения</div>
          {data.platforms.length === 0 ? (
            <div className="gd-sub">Пока ничего</div>
          ) : (
            <div className="gd-rows">
              {data.platforms.map((p) => (
                <div key={`${p.platform}-${p.appVersion}`} className="gd-r">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>
                      {PLATFORM[p.platform] || p.platform} <span className="gd-chip">{p.appVersion || "?"}</span>
                    </div>
                    <div className="gd-cellsub">{num(p.attempts)} попыток · медиана {ms(p.medianMs)}</div>
                  </div>
                  <div className="r" style={{ color: okColor(p.okPct, p.attempts), fontWeight: 600 }}>
                    {p.okPct}%
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card pad>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Частые ошибки</div>
          {data.errors.length === 0 ? (
            <div className="gd-sub">Ошибок не присылали</div>
          ) : (
            <div className="gd-rows">
              {data.errors.map((e) => (
                <div key={e.error} className="gd-r">
                  <div style={{ minWidth: 0, fontSize: 13.5 }}>{e.error}</div>
                  <div className="r gd-num">{num(e.count)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card pad>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Последние неудачи</div>
        <div className="gd-sub" style={{ marginBottom: 12 }}>
          По одной попытке: где, чем и на какой стадии оборвалось
        </div>
        {data.recentFailures.length === 0 ? (
          <div className="gd-sub">Неудач нет</div>
        ) : (
          <div className="gd-rows">
            {data.recentFailures.map((f, i) => (
              <div key={i} className="gd-r">
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {PROTO[f.protocol] || f.protocol} → {f.server}
                    {f.port ? <span className="gd-chip">:{f.port}</span> : null}
                    <Chip color="var(--gd-warn)">{f.stage}</Chip>
                  </div>
                  <div className="gd-cellsub">
                    {PLATFORM[f.platform] || f.platform} {f.appVersion || ""} · {KIND[f.networkKind] || f.networkKind}
                    {f.operator ? ` · ${f.operator}` : ""} · {f.attempts} поп. · {ms(f.durationMs)}
                    {f.error ? ` · ${f.error}` : ""}
                  </div>
                </div>
                <div className="r" style={{ color: "var(--gd-dim)", fontSize: 13 }}>{ago(f.at)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function best(protocols) {
  const eligible = protocols.filter((p) => p.attempts >= 5);
  if (!eligible.length) return "—";
  const top = eligible.reduce((a, b) => (b.okPct > a.okPct ? b : a));
  return `${PROTO[top.protocol] || top.protocol} · ${top.okPct}%`;
}

function IconValue({ icon, children }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
      <span style={{ color: "var(--gd-gold)", display: "inline-flex" }}>{icon}</span>
      {children}
    </span>
  );
}

function Matrix({ rows, cols, get, rowLabel }) {
  if (!rows.length) return <div className="gd-sub">Пока ничего</div>;
  return (
    <div className="gd-table-wrap">
      <table className="gd-table fn-table">
        <thead>
          <tr>
            <th />
            {cols.map((c) => (
              <th key={c} className="num">
                {PROTO[c] || c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r} style={{ cursor: "default" }}>
              <td>{rowLabel(r)}</td>
              {cols.map((c) => {
                const cell = get(r, c);
                if (!cell) {
                  return (
                    <td key={c} className="num" style={{ color: "var(--gd-faint)" }}>
                      —
                    </td>
                  );
                }
                return (
                  <td key={c} className="num">
                    <span style={{ color: okColor(cell.okPct, cell.attempts), fontWeight: 600 }}>{cell.okPct}%</span>
                    <span style={{ color: "var(--gd-faint)", marginLeft: 6, fontSize: 12 }}>
                      {cell.ok}/{cell.attempts} · {ms(cell.medianMs)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
