import { Search, X } from "lucide-react";

// Базовые кирпичики «золотого» кита. Разметка и классы — из дизайн-системы,
// поведение минимальное: всё сложное живёт в страницах.

export function Card({ children, pad = false, className = "", style, ...rest }) {
  return (
    <div className={`gd-card${pad ? " gd-pad" : ""} ${className}`.trim()} style={style} {...rest}>
      {children}
    </div>
  );
}

export function Tile({ label, value, sub, dot, className = "", style }) {
  return (
    <div className={`gd-tile ${className}`.trim()} style={style}>
      <div className="gd-tile-top">
        {dot && <span className="gd-dot" style={{ background: dot }} />}
        <div className="gd-tile-v gd-num">{value}</div>
      </div>
      <div className="gd-tile-l">{label}</div>
      {sub && <div className="gd-tile-l" style={{ marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export function Dot({ color, size = 8, glow = false }) {
  return (
    <span
      className="gd-dot"
      style={{
        width: size,
        height: size,
        background: color,
        boxShadow: glow ? `0 0 8px ${color}` : undefined,
      }}
    />
  );
}

export function Chip({ children, color, background, style }) {
  return (
    <span
      className="gd-chip"
      style={{
        color: color || undefined,
        background: background || (color ? `color-mix(in srgb, ${color} 15%, transparent)` : undefined),
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export function StatusDot({ color, label, glow }) {
  return (
    <span className="gd-status">
      <Dot color={color} glow={glow} />
      {label}
    </span>
  );
}

export function Button({ variant = "", size = "", children, ...rest }) {
  const cls = ["gd-btn", variant, size === "sm" ? "sm" : ""].filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} {...rest}>
      {children}
    </button>
  );
}

export function Field({ label, children, hint, style }) {
  return (
    <label style={{ display: "block", minWidth: 0, ...style }}>
      {label && <span className="gd-field-l">{label}</span>}
      {children}
      {hint && (
        <span className="gd-tile-l" style={{ marginTop: 6, display: "block", whiteSpace: "normal" }}>
          {hint}
        </span>
      )}
    </label>
  );
}

export function SearchInput({ value, onChange, placeholder = "Поиск", style }) {
  return (
    <div className="gd-search" style={style}>
      <Search className="ico" size={15} />
      <input
        className="gd-input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        // Поиск — самое частое действие на странице пользователей,
        // поэтому Esc чистит его, не уводя фокус.
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.stopPropagation();
            onChange("");
          }
        }}
      />
      {value && (
        <button className="gd-search-clear" onClick={() => onChange("")} aria-label="Очистить">
          <X size={15} />
        </button>
      )}
    </div>
  );
}

export function Seg({ options, value, onChange, gold = false, full = false }) {
  return (
    <div className={`gd-seg${gold ? " gold" : ""}`} style={full ? { display: "flex", width: "100%" } : undefined}>
      {options.map((option) => (
        <button
          key={option.id}
          className={option.id === value ? "active" : ""}
          onClick={() => onChange(option.id)}
          style={full ? { flex: 1 } : undefined}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ on, onChange, disabled, title }) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      className={`gd-sw${on ? " on" : ""}`}
      aria-pressed={on}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
    />
  );
}

export function KV({ k, children, mono = false }) {
  return (
    <div className="gd-kv">
      <span className="gd-kv-k">{k}</span>
      <span className={`gd-kv-v${mono ? " gd-mono" : ""}`}>{children}</span>
    </div>
  );
}

export function Avatar({ children }) {
  return <div className="gd-avatar">{children}</div>;
}

export function Bar({ pct, color }) {
  const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
  return (
    <div className="gd-bar">
      <span style={{ width: `${clamped}%`, background: color }} />
    </div>
  );
}

export function Loading({ text = "Загружаем" }) {
  return (
    <div className="gd-loading">
      <span className="gd-spin" />
      {text}
    </div>
  );
}

export function Empty({ children = "Ничего не нашлось" }) {
  return <div className="gd-empty">{children}</div>;
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="gd-error">
      <span>{error.message || "Что-то пошло не так"}</span>
      {onRetry && (
        <Button size="sm" style={{ marginLeft: "auto" }} onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}

export function PageHead({ title, sub, children }) {
  return (
    <div className="gd-head">
      <div>
        <h1 className="gd-title">{title}</h1>
        {sub && <div className="gd-sub">{sub}</div>}
      </div>
      {children && <div className="gd-head-right">{children}</div>}
    </div>
  );
}

export function Section({ title, sub, children, actions }) {
  return (
    <div>
      {(title || actions) && (
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
          <div>
            {title && <div className="gd-sec-title">{title}</div>}
            {sub && <div className="gd-sec-sub">{sub}</div>}
          </div>
          {actions && <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/** Строка меню «параметр · состояние · действие» — основа блока управления. */
export function MenuRow({ title, sub, children }) {
  return (
    <div className="gd-mrow">
      <div className="gd-mrow-l">
        <div className="gd-mrow-t">{title}</div>
        {sub && <div className="gd-mrow-s">{sub}</div>}
      </div>
      <div className="gd-mrow-r">{children}</div>
    </div>
  );
}

export function Copyable({ text, children }) {
  const value = (text ?? "").toString();
  if (!value) return <span style={{ color: "var(--gd-faint)" }}>—</span>;
  return (
    <button
      type="button"
      className="gd-mono"
      title="Скопировать"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(value).catch(() => {});
        const el = e.currentTarget.querySelector("[data-mark]");
        if (el) {
          el.textContent = "✓";
          setTimeout(() => {
            el.textContent = "⧉";
          }, 1100);
        }
      }}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        maxWidth: "100%",
        background: "transparent",
        border: 0,
        padding: 0,
        cursor: "pointer",
        color: "inherit",
        font: "inherit",
      }}
    >
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {children ?? value}
      </span>
      <span data-mark style={{ fontSize: 10, color: "var(--gd-faint)", flexShrink: 0 }}>
        ⧉
      </span>
    </button>
  );
}
