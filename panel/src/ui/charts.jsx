const GOLD = "var(--gd-gold)";

export function Spark({ data, color = GOLD, height = 56, width = 260, fill = true, strokeWidth = 2 }) {
  const n = data.length;
  if (!n) return <svg width={width} height={height} />;

  const max = Math.max(...data, 1);
  const padY = 4;
  const x = (i) => (n === 1 ? width / 2 : (i / (n - 1)) * width);
  const y = (v) => height - padY - (v / max) * (height - padY * 2);
  const points = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const gradientId = `spark-${Math.round(width)}-${n}`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: "block", width: "100%" }}
    >
      {fill && (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.22" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`M0,${height} L${points.join(" L")} L${width},${height} Z`} fill={`url(#${gradientId})`} />
        </>
      )}
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function Bars({ data, color = GOLD, height = 64, highlightMax = true, onHover }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  const maxIndex = data.reduce((mi, d, i, a) => (d.value > a[mi].value ? i : mi), 0);

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height }}>
      {data.map((d, i) => (
        <div
          key={i}
          title={d.label}
          onMouseEnter={onHover ? () => onHover(d, i) : undefined}
          onMouseLeave={onHover ? () => onHover(null, -1) : undefined}
          style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}
        >
          <div
            style={{
              height: `${Math.max(3, (d.value / max) * 100)}%`,
              borderRadius: 3,
              background:
                highlightMax && i === maxIndex ? color : `color-mix(in srgb, ${color} 34%, transparent)`,
              transition: "height .5s ease",
            }}
          />
        </div>
      ))}
    </div>
  );
}

export function Donut({ segments, size = 132, thickness = 15, centerValue, centerLabel }) {
  const r = (size - thickness) / 2;
  const circumference = 2 * Math.PI * r;
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0);
  const cx = size / 2;
  let acc = 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--gd-tile)" strokeWidth={thickness} />
      <g transform={`rotate(-90 ${cx} ${cx})`}>
        {total > 0 &&
          segments
            .filter((s) => s.value > 0)
            .map((s, i) => {
              const len = (s.value / total) * circumference;
              const el = (
                <circle
                  key={i}
                  cx={cx}
                  cy={cx}
                  r={r}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={thickness}
                  strokeDasharray={`${len.toFixed(2)} ${(circumference - len).toFixed(2)}`}
                  strokeDashoffset={(-acc).toFixed(2)}
                  strokeLinecap="butt"
                />
              );
              acc += len;
              return el;
            })}
      </g>
      {centerValue != null && (
        <text
          x={cx}
          y={cx - 2}
          textAnchor="middle"
          fill="var(--gd-text)"
          fontSize={size * 0.19}
          fontWeight="700"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {centerValue}
        </text>
      )}
      {centerLabel != null && (
        <text x={cx} y={cx + size * 0.14} textAnchor="middle" fill="var(--gd-faint)" fontSize={size * 0.085}>
          {centerLabel}
        </text>
      )}
    </svg>
  );
}

export function Ring({ pct, size = 76, thickness = 8, color = GOLD, children }) {
  const r = (size - thickness) / 2;
  const circumference = 2 * Math.PI * r;
  const cx = size / 2;
  const len = (Math.max(0, Math.min(100, pct)) / 100) * circumference;

  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--gd-tile)" strokeWidth={thickness} />
        <g transform={`rotate(-90 ${cx} ${cx})`}>
          <circle
            cx={cx}
            cy={cx}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={thickness}
            strokeDasharray={`${len.toFixed(2)} ${(circumference - len).toFixed(2)}`}
            strokeLinecap="round"
          />
        </g>
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
        {children}
      </div>
    </div>
  );
}

export function DonutLegend({ items, format }) {
  const total = items.reduce((s, x) => s + Math.max(0, x.value), 0);
  const fmt = format || ((v) => String(Math.round(v)));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9, minWidth: 0, flex: 1 }}>
      {items
        .filter((x) => x.value > 0)
        .map((x, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13 }}>
            <span className="gd-dot" style={{ background: x.color }} />
            <span
              style={{ color: "var(--gd-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {x.label}
            </span>
            <span className="gd-num" style={{ marginLeft: "auto", fontWeight: 600 }}>
              {fmt(x.value)}
            </span>
            <span className="gd-num" style={{ color: "var(--gd-faint)", width: 42, textAlign: "right" }}>
              {total > 0 ? Math.round((x.value / total) * 100) : 0}%
            </span>
          </div>
        ))}
    </div>
  );
}

export function Trend({ pct }) {
  if (pct == null || !isFinite(pct)) return null;
  const positive = pct >= 0;
  return (
    <span className={`gd-trend ${positive ? "pos" : "neg"}`}>
      {positive ? "↗" : "↘"} {Math.abs(pct).toFixed(1)}%
    </span>
  );
}
