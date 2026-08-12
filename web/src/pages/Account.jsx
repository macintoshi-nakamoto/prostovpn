import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { api, ApiError } from "../lib/api";
import { useDismiss } from "../lib/hooks";
import { bytes, days, longDate, money, shortDate, ago } from "../lib/format";
import { SetupGuide } from "../components/SetupGuide.jsx";
import { Picture } from "../components/Picture.jsx";
import { PasswordDialog } from "../components/PasswordDialog.jsx";
import "./account.css";

const TABS = [
  { id: "account", label: "Аккаунт" },
  { id: "plan", label: "Подписка" },
  { id: "setup", label: "Инструкция по установке" },
];

const HEADS = {
  account: ["Аккаунт", "Подписка, устройства и данные для входа"],
  plan: ["Подписка", "Тариф, платежи и продление"],
  setup: ["Инструкция по установке", "Пошагово для каждой платформы"],
};

export function Account() {
  const { signOut } = useSession();
  const navigate = useNavigate();
  const [tab, setTab] = useState("account");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const menuRef = useDismiss(menuOpen, () => setMenuOpen(false));

  const load = useCallback(async () => {
    try {
      setData(await api.account());
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate("/login", { replace: true });
        return;
      }
      setError("Не удалось загрузить данные аккаунта");
    }
  }, [navigate]);

  useEffect(() => {
    load();
  }, [load]);

  const logout = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  const [tab1, tab2, tab3] = TABS;
  const [title, subtitle] = HEADS[tab];

  return (
    <div className="ac">
      <header className="ac-header">
        <div className="wrap ac-header-in">
          <Link to="/" className="ac-logo">
            <Picture src="/assets/logo.png" alt="PROSTO" />
          </Link>
          <nav className="ac-tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? "active" : ""}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="ac-user" ref={menuRef}>
            <button
              className={`ac-user-btn${menuOpen ? " open" : ""}`}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span className="ac-avatar">P</span>
              {data?.login || "аккаунт"}
              <span className="ac-caret">▼</span>
            </button>
            {menuOpen && (
              <div className="ac-menu">
                <span className="ac-menu-head">
                  <span className="ac-menu-login">{data?.login}</span>
                  <span className="ac-menu-status">
                    {data?.active ? "Подписка активна" : "Подписка неактивна"}
                  </span>
                </span>
                <span className="ac-menu-sep" />
                <button
                  className="ac-menu-item"
                  onClick={() => {
                    setMenuOpen(false);
                    setPwOpen(true);
                  }}
                >
                  Сменить пароль
                </button>
                <button className="ac-menu-item ac-menu-danger" onClick={logout}>
                  Выйти
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="wrap ac-main">
        <div className="ac-title">
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>

        {error && <div className="ac-error">{error}</div>}

        {data && tab === "account" && (
          <AccountTab data={data} onManage={() => setTab("plan")} onSetup={() => setTab("setup")} onPassword={() => setPwOpen(true)} onChanged={load} />
        )}
        {data && tab === "plan" && <PlanTab data={data} onChanged={load} />}
        {data && tab === "setup" && <SetupGuide login={data.login} />}
      </main>

      <PasswordDialog
        open={pwOpen}
        onClose={() => setPwOpen(false)}
        onDone={async () => {
          setPwOpen(false);
          // Смена пароля гасит все сессии — уходим на вход.
          await signOut();
          navigate("/login", { replace: true });
        }}
      />
    </div>
  );
}

function AccountTab({ data, onManage, onSetup, onPassword, onChanged }) {
  const used = data.devices.length;
  const free = Math.max(0, data.device_limit - used);
  const traffic = data.traffic_limit_bytes
    ? `${bytes(data.traffic_used_bytes)} из ${bytes(data.traffic_limit_bytes)}`
    : bytes(data.traffic_used_bytes);

  return (
    <div className="ac-account">
      <div className="ac-hero">
        <div className="ac-hero-body">
          <span className="ac-hero-status">
            <span className="ac-dot" />
            {data.active ? "Подписка активна" : "Подписка неактивна"}
          </span>
          <span className="ac-hero-plan">
            {data.plan_title ? `Prosto VPN · ${data.plan_title}` : "Без тарифа"}
          </span>
          <span className="ac-hero-sub">
            {data.expires_at
              ? `Действует до ${longDate(data.expires_at)}${
                  data.days_left != null ? ` · осталось ${days(data.days_left)}` : ""
                }`
              : "Оформите подписку, чтобы начать"}
          </span>
        </div>
        <button className="ac-hero-btn" onClick={onManage}>
          Управлять подпиской
        </button>
      </div>

      <div className="ac-stats">
        <div className="ac-stat">
          <span className="ac-stat-l">Устройства</span>
          <span className="ac-stat-v">
            {used} из {data.device_limit}
          </span>
          <span className="ac-stat-s">
            {free > 0 ? `Свободно ${plshort(free)}` : "Мест не осталось"}
          </span>
        </div>
        <div className="ac-stat">
          <span className="ac-stat-l">Трафик</span>
          <span className="ac-stat-v">{bytes(data.traffic_used_bytes)}</span>
          <span className="ac-stat-s">
            {data.traffic_limit_bytes ? `из ${bytes(data.traffic_limit_bytes)}` : "Без ограничений по тарифу"}
          </span>
        </div>
        <div className="ac-stat">
          <span className="ac-stat-l">Публичный ID</span>
          <span className="ac-stat-v ac-stat-mono">{data.public_id}</span>
          <span className="ac-stat-s">Назовите его в поддержке</span>
        </div>
      </div>

      <div className="ac-columns">
        <div className="ac-card">
          <div className="ac-card-head">
            <h2>Подключённые устройства</h2>
            <button className="ac-link" onClick={onSetup}>
              Добавить
            </button>
          </div>
          {used === 0 ? (
            <p className="ac-empty">Пока ни одного входа. Установите приложение и войдите теми же логином и паролем.</p>
          ) : (
            <div className="ac-devices">
              {data.devices.map((d) => (
                <DeviceRow key={d.id} device={d} onChanged={onChanged} />
              ))}
            </div>
          )}
        </div>

        <div className="ac-card">
          <h2>Данные аккаунта</h2>
          <div className="ac-kvs">
            <div className="ac-kv">
              <span>Логин</span>
              <b>{data.login}</b>
            </div>
            <div className="ac-kv">
              <span>Пароль</span>
              <b>••••••••</b>
            </div>
            <EmailRow email={data.email} onChanged={onChanged} />
          </div>
          <button className="btn btn-outline btn-block" onClick={onPassword}>
            Сменить пароль
          </button>
        </div>
      </div>
    </div>
  );
}

function plshort(n) {
  return `${n} ${["подключение", "подключения", "подключений"][n === 1 ? 0 : n > 1 && n < 5 ? 1 : 2]}`;
}

/**
 * Почта для чеков: показать, добавить, сменить.
 *
 * Учётка из регистрации рождается без почты, и продление упиралось в
 * «нет почты» без возможности её дать. Форма живёт прямо в строке: для
 * одного поля отдельная модалка — это лишний экран.
 */
function EmailRow({ email, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.setEmail(value.trim());
      setEditing(false);
      setValue("");
      onChanged();
    } catch (err) {
      // Код причины точнее сырого текста бэкенда: его можно перевести.
      const code = err instanceof ApiError ? err.code : "";
      setError(
        code === "email_taken"
          ? "Эта почта уже привязана к другой учётке"
          : err instanceof ApiError
            ? err.message
            : "Не удалось сохранить почту",
      );
    } finally {
      setBusy(false);
    }
  };

  if (!editing) {
    return (
      <div className="ac-kv">
        <span>Почта для чеков</span>
        <b>
          {email || "не указана"}{" "}
          <button
            className="ac-link"
            type="button"
            onClick={() => {
              setValue(email || "");
              setError("");
              setEditing(true);
            }}
          >
            {email ? "изменить" : "добавить"}
          </button>
        </b>
      </div>
    );
  }

  return (
    <form className="ac-kv ac-kv-form" onSubmit={save}>
      <span>Почта для чеков</span>
      <div className="ac-email-edit">
        <input
          type="email"
          required
          autoFocus
          placeholder="you@example.com"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={busy}
        />
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "…" : "Сохранить"}
        </button>
        <button
          className="btn btn-outline"
          type="button"
          disabled={busy}
          onClick={() => setEditing(false)}
        >
          Отмена
        </button>
      </div>
      {error && <p className="ac-email-error">{error}</p>}
    </form>
  );
}

function DeviceRow({ device, onChanged }) {
  const [busy, setBusy] = useState(false);
  const unlink = async () => {
    setBusy(true);
    try {
      await api.unlinkDevice(device.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  const platform = { windows: "Windows", android: "Android", ios: "iOS", macos: "macOS", web: "Браузер" };
  return (
    <div className="ac-device">
      <span className="ac-device-body">
        <span className="ac-device-name">{device.name || platform[device.platform] || "Устройство"}</span>
        <span className="ac-device-sub">
          {(platform[device.platform] || device.platform || "").toString()}
          {device.is_current ? " · это устройство" : ` · ${ago(device.last_seen_at)}`}
        </span>
      </span>
      {!device.is_current && (
        <button className="ac-device-off" disabled={busy} onClick={unlink}>
          Отключить
        </button>
      )}
    </div>
  );
}

function PlanTab({ data, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const renew = async () => {
    setBusy(true);
    setNotice("");
    try {
      await api.renew(data.plan);
      setNotice("Заказ на продление создан. Оплата подключается — мы напишем, когда она заработает.");
      onChanged();
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Не удалось создать заказ");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ac-plan">
      <div className="ac-plan-summary">
        <div>
          <span className="ac-plan-l">Тариф</span>
          <span className="ac-plan-v">{data.plan_title || "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">Срок</span>
          <span className="ac-plan-v">{data.period_days ? days(data.period_days) : "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">Действует до</span>
          <span className="ac-plan-v">{data.expires_at ? shortDate(data.expires_at) : "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">Осталось</span>
          <span className="ac-plan-v ac-accent">{data.days_left != null ? days(data.days_left) : "—"}</span>
        </div>
      </div>

      <div className="ac-card ac-renew">
        <div className="ac-renew-body">
          <h2>Продлить подписку</h2>
          <p>
            Продление добавит {data.period_days ? days(data.period_days) : "срок тарифа"} к текущей подписке.
            {data.price ? ` Стоимость — ${money(data.price)}.` : ""}
          </p>
        </div>
        <button className="btn btn-primary ac-renew-btn" disabled={busy} onClick={renew}>
          {busy ? "Создаём заказ…" : "Продлить"}
        </button>
      </div>
      {notice && <div className="ac-notice">{notice}</div>}

      <div className="ac-card">
        <h2>История платежей</h2>
        {data.payments.length === 0 ? (
          <p className="ac-empty">Платежей пока не было.</p>
        ) : (
          <div className="ac-pay">
            <div className="ac-pay-row ac-pay-head">
              <span>Дата</span>
              <span>Описание</span>
              <span>Сумма</span>
            </div>
            {data.payments.map((p, i) => (
              <div className="ac-pay-row" key={i}>
                <span>{longDate(p.paid_at)}</span>
                <span className="ac-pay-desc">{p.comment || "Оплата"}</span>
                <span className="ac-pay-sum">{money(p.amount, p.currency)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
