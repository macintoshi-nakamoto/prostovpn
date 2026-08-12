import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { api, ApiError } from "../lib/api";
import { useDismiss } from "../lib/hooks";
import { SetupGuide } from "../components/SetupGuide.jsx";
import { Picture } from "../components/Picture.jsx";
import { Controls } from "../components/Controls.jsx";
import { PasswordDialog } from "../components/PasswordDialog.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./account.css";

// Порядок вкладок — здесь, подписи к ним — в словаре.
const TABS = ["account", "plan", "setup"];

export function Account() {
  const { t, raw } = useI18n();
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
      setError(t("account.loadError"));
    }
  }, [navigate, t]);

  useEffect(() => {
    load();
  }, [load]);

  const logout = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  const [title, subtitle] = raw(`account.heads.${tab}`);

  return (
    <div className="ac">
      <header className="ac-header">
        <div className="wrap ac-header-in">
          <Link to="/" className="ac-logo">
            <Picture src="/assets/logo.png" alt="PROSTO" />
          </Link>
          <nav className="ac-tabs">
            {TABS.map((id) => (
              <button
                key={id}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id)}
              >
                {t(`account.tabs.${id}`)}
              </button>
            ))}
          </nav>
          <Controls />
          <div className="ac-user" ref={menuRef}>
            <button
              className={`ac-user-btn${menuOpen ? " open" : ""}`}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span className="ac-avatar">P</span>
              {data?.login || t("account.fallbackName")}
              <span className="ac-caret">▼</span>
            </button>
            {menuOpen && (
              <div className="ac-menu">
                <span className="ac-menu-head">
                  <span className="ac-menu-login">{data?.login}</span>
                  <span className="ac-menu-status">
                    {data?.active ? t("account.active") : t("account.inactive")}
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
                  {t("account.changePassword")}
                </button>
                <button className="ac-menu-item ac-menu-danger" onClick={logout}>
                  {t("account.signOut")}
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
          <AccountTab
            data={data}
            onManage={() => setTab("plan")}
            onSetup={() => setTab("setup")}
            onPassword={() => setPwOpen(true)}
            onChanged={load}
          />
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
  const { t, f } = useI18n();
  const used = data.devices.length;
  const free = Math.max(0, data.device_limit - used);

  return (
    <div className="ac-account">
      <div className="ac-hero">
        <div className="ac-hero-body">
          <span className="ac-hero-status">
            <span className="ac-dot" />
            {data.active ? t("account.active") : t("account.inactive")}
          </span>
          <span className="ac-hero-plan">
            {data.plan_title ? `Prosto VPN · ${data.plan_title}` : t("account.noPlan")}
          </span>
          <span className="ac-hero-sub">
            {data.expires_at
              ? t(data.days_left != null ? "account.validUntilLeft" : "account.validUntil", {
                  date: f.longDate(data.expires_at),
                  left: f.days(data.days_left),
                })
              : t("account.subscribePrompt")}
          </span>
        </div>
        <button className="ac-hero-btn" onClick={onManage}>
          {t("account.manage")}
        </button>
      </div>

      <div className="ac-stats">
        <div className="ac-stat">
          <span className="ac-stat-l">{t("account.statDevices")}</span>
          <span className="ac-stat-v">
            {t("account.statOf", { used, total: data.device_limit })}
          </span>
          <span className="ac-stat-s">
            {free > 0
              ? t("account.freeSlots", { value: t("units.connections", { count: free }) })
              : t("account.noSlots")}
          </span>
        </div>
        <div className="ac-stat">
          <span className="ac-stat-l">{t("account.statTraffic")}</span>
          <span className="ac-stat-v">{f.bytes(data.traffic_used_bytes)}</span>
          <span className="ac-stat-s">
            {data.traffic_limit_bytes
              ? t("account.trafficOf", { total: f.bytes(data.traffic_limit_bytes) })
              : t("account.trafficUnlimited")}
          </span>
        </div>
        <div className="ac-stat">
          <span className="ac-stat-l">{t("account.statPublicId")}</span>
          <span className="ac-stat-v ac-stat-mono">{data.public_id}</span>
          <span className="ac-stat-s">{t("account.publicIdHint")}</span>
        </div>
      </div>

      <div className="ac-columns">
        <div className="ac-card">
          <div className="ac-card-head">
            <h2>{t("account.devicesTitle")}</h2>
            <button className="ac-link" onClick={onSetup}>
              {t("account.devicesAdd")}
            </button>
          </div>
          {used === 0 ? (
            <p className="ac-empty">{t("account.devicesEmpty")}</p>
          ) : (
            <div className="ac-devices">
              {data.devices.map((d) => (
                <DeviceRow key={d.id} device={d} onChanged={onChanged} />
              ))}
            </div>
          )}
        </div>

        <div className="ac-card">
          <h2>{t("account.dataTitle")}</h2>
          <div className="ac-kvs">
            <div className="ac-kv">
              <span>{t("account.fieldLogin")}</span>
              <b>{data.login}</b>
            </div>
            <div className="ac-kv">
              <span>{t("account.fieldPassword")}</span>
              <b>••••••••</b>
            </div>
            <EmailRow email={data.email} onChanged={onChanged} />
          </div>
          <button className="btn btn-outline btn-block" onClick={onPassword}>
            {t("account.changePassword")}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Почта для чеков: показать, добавить, сменить.
 *
 * Учётка из регистрации рождается без почты, и продление упиралось в
 * «нет почты» без возможности её дать. Форма живёт прямо в строке: для
 * одного поля отдельная модалка — это лишний экран.
 */
function EmailRow({ email, onChanged }) {
  const { t } = useI18n();
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
          ? t("account.emailTaken")
          : err instanceof ApiError
            ? err.message
            : t("account.emailFailed"),
      );
    } finally {
      setBusy(false);
    }
  };

  if (!editing) {
    return (
      <div className="ac-kv">
        <span>{t("account.fieldEmail")}</span>
        <b>
          {email || t("account.emailEmpty")}{" "}
          <button
            className="ac-link"
            type="button"
            onClick={() => {
              setValue(email || "");
              setError("");
              setEditing(true);
            }}
          >
            {email ? t("account.emailChange") : t("account.emailAdd")}
          </button>
        </b>
      </div>
    );
  }

  return (
    <form className="ac-kv ac-kv-form" onSubmit={save}>
      <span>{t("account.fieldEmail")}</span>
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
          {busy ? "…" : t("account.save")}
        </button>
        <button
          className="btn btn-outline"
          type="button"
          disabled={busy}
          onClick={() => setEditing(false)}
        >
          {t("account.cancel")}
        </button>
      </div>
      {error && <p className="ac-email-error">{error}</p>}
    </form>
  );
}

function DeviceRow({ device, onChanged }) {
  const { t, f } = useI18n();
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
  // Названия платформ не переводятся — кроме браузера, который не бренд.
  const platform = {
    windows: "Windows",
    android: "Android",
    ios: "iOS",
    macos: "macOS",
    web: t("account.platformWeb"),
  };
  return (
    <div className="ac-device">
      <span className="ac-device-body">
        <span className="ac-device-name">
          {device.name || platform[device.platform] || t("account.deviceFallback")}
        </span>
        <span className="ac-device-sub">
          {(platform[device.platform] || device.platform || "").toString()}
          {device.is_current
            ? ` · ${t("account.thisDevice")}`
            : ` · ${f.ago(device.last_seen_at)}`}
        </span>
      </span>
      {!device.is_current && (
        <button className="ac-device-off" disabled={busy} onClick={unlink}>
          {t("account.disconnect")}
        </button>
      )}
    </div>
  );
}

function PlanTab({ data, onChanged }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const renew = async () => {
    setBusy(true);
    setNotice("");
    try {
      await api.renew(data.plan);
      setNotice(t("account.renewCreated"));
      onChanged();
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : t("account.renewFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ac-plan">
      <div className="ac-plan-summary">
        <div>
          <span className="ac-plan-l">{t("account.planTitle")}</span>
          <span className="ac-plan-v">{data.plan_title || "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">{t("account.planTerm")}</span>
          <span className="ac-plan-v">{data.period_days ? f.days(data.period_days) : "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">{t("account.planUntil")}</span>
          <span className="ac-plan-v">{data.expires_at ? f.shortDate(data.expires_at) : "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">{t("account.planLeft")}</span>
          <span className="ac-plan-v ac-accent">
            {data.days_left != null ? f.days(data.days_left) : "—"}
          </span>
        </div>
      </div>

      <div className="ac-card ac-renew">
        <div className="ac-renew-body">
          <h2>{t("account.renewTitle")}</h2>
          <p>
            {t("account.renewText", {
              term: data.period_days
                ? f.days(data.period_days)
                : t("account.renewTermFallback"),
            })}
            {data.price ? t("account.renewPrice", { price: f.money(data.price) }) : ""}
          </p>
        </div>
        <button className="btn btn-primary ac-renew-btn" disabled={busy} onClick={renew}>
          {busy ? t("account.renewBusy") : t("account.renew")}
        </button>
      </div>
      {notice && <div className="ac-notice">{notice}</div>}

      <div className="ac-card">
        <h2>{t("account.paymentsTitle")}</h2>
        {data.payments.length === 0 ? (
          <p className="ac-empty">{t("account.paymentsEmpty")}</p>
        ) : (
          <div className="ac-pay">
            <div className="ac-pay-row ac-pay-head">
              <span>{t("account.payDate")}</span>
              <span>{t("account.payDesc")}</span>
              <span>{t("account.paySum")}</span>
            </div>
            {data.payments.map((p, i) => (
              <div className="ac-pay-row" key={i}>
                <span>{f.longDate(p.paid_at)}</span>
                <span className="ac-pay-desc">{p.comment || t("account.payFallback")}</span>
                <span className="ac-pay-sum">{f.money(p.amount, p.currency)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
