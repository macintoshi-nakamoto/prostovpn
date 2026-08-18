import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
  /*
  Вкладка и выбранный тариф приходят в адресе.

  С лендинга сюда ведут кнопки «Выбрать» на карточках тарифов и «App Store»
  из подвала: человек уже сказал, за чем пришёл, и открывать ему общую
  вкладку значит просить сказать это второй раз. Гость по дороге проходит
  через форму входа, и запрос переживает её — см. Login.jsx.
  */
  const [params] = useSearchParams();
  const wantedTab = TABS.includes(params.get("tab")) ? params.get("tab") : "account";
  const wantedPlan = params.get("plan") || "";
  const [tab, setTab] = useState(wantedTab);
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

  /*
  Ответ действия — это и есть свежий кабинет.

  Выдача ключа, удаление, отвязка устройства возвращают тот же объект, что и
  `/account`, поэтому подставляем его сразу. Второй запрос следом стоил бы
  сотни миллисекунд, в которые человек видит список без ключа, который он
  только что создал, — и жмёт кнопку второй раз.
  */
  const apply = useCallback((fresh) => {
    if (fresh) setData(fresh);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /*
  Освежаем кабинет сами, пока страница открыта.

  Ключи выдаёт не только сам человек: их заводит поддержка из панели, туда
  же приходит продление, и подписка может закончиться прямо во время того,
  как страница открыта. Просить за этим F5 значит показывать вчерашнее
  состояние тому, кто сидит и смотрит.

  Свой запрос раз в пятнадцать секунд плюс один в момент возвращения к
  вкладке. Проверку `visibilityState` здесь не ставим намеренно: в скрытой
  вкладке браузер сам разжимает таймеры до раза в минуту, а вот
  «постоянно скрытых» контекстов — встроенных вебвью, окон без фокуса —
  хватает, и в них проверка выключала бы обновление насовсем.
  */
  useEffect(() => {
    const timer = setInterval(load, 15000);
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
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
            <Picture src="/assets/logo-v3.png" alt="PROSTO" />
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
            onApply={apply}
          />
        )}
        {data && tab === "plan" && (
          <PlanTab data={data} preselected={wantedPlan} onChanged={load} />
        )}
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

function AccountTab({ data, onManage, onSetup, onPassword, onChanged, onApply }) {
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

      <IosCard ios={data.ios} active={data.active} onApply={onApply} onManage={onManage} />

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
 * Ключи AmneziaVPN для iPhone.
 *
 * На iPhone нашего приложения нет, и ключ `vpn://` — единственный способ
 * подключиться. Поэтому карточка живёт в кабинете рядом с устройствами, а
 * не прячется в инструкции: то, чем человек пользуется каждый день, должно
 * лежать там, куда он заходит.
 *
 * Ключей до пяти, по одному на устройство. Один пир нельзя честно поделить
 * между телефонами — сервер помнит у пира один адрес подключения, и второй
 * телефон молча отбирает туннель у первого, — поэтому «ещё один телефон»
 * это кнопка «Добавить ключ», а не тот же ключ, вставленный дважды.
 *
 * Каждое действие возвращает кабинет целиком, и список перерисовывается
 * ответом сервера. Своего состояния у карточки нет вовсе: ключ появляется
 * ровно тогда, когда пир заведён на узле, а не когда нажата кнопка.
 */
function IosCard({ ios, active, onApply, onManage }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const keys = ios?.keys || [];
  const total = ios?.max_keys || 5;
  const used = ios?.keys_count || 0;

  const run = async (call, fallback) => {
    setBusy(true);
    setError("");
    try {
      onApply(await call());
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setError(
        code === "no_subscription"
          ? t("account.iosNoSubscription")
          : err instanceof ApiError
            ? err.message
            : fallback,
      );
    } finally {
      setBusy(false);
    }
  };

  // Ключа ещё нет: показываем предложение, а не пустую карточку. Кнопка
  // ведёт к подписке, если платить ещё нечем: отказ «нет подписки» после
  // нажатия говорит то же самое, но на шаг позже.
  if (!ios?.available) {
    return (
      <div className="ac-card ac-ios">
        <div className="ac-card-head">
          <h2>{t("account.iosTitle")}</h2>
        </div>
        <p className="ac-empty">{t("account.iosOffer")}</p>
        {error && <p className="ac-ios-error">{error}</p>}
        <div className="ac-ios-foot">
          {active ? (
            <button
              className="btn btn-primary"
              disabled={busy}
              onClick={() => run(api.enableIos, t("account.iosFailed"))}
            >
              {busy ? t("account.iosGetBusy") : t("account.iosGet")}
            </button>
          ) : (
            <button className="btn btn-primary" onClick={onManage}>
              {t("account.manage")}
            </button>
          )}
          <Link className="ac-link" to="/guide">
            {t("account.iosGuide")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="ac-card ac-ios">
      <div className="ac-card-head">
        <h2>{t("account.iosTitle")}</h2>
        <span className="ac-ios-count">{t("account.iosCount", { used, total })}</span>
      </div>
      <p className="ac-ios-sub">{t("account.iosSub")}</p>

      {ios.notice && <p className="ac-ios-notice">{ios.notice}</p>}
      {error && <p className="ac-ios-error">{error}</p>}

      {keys.length > 0 && (
        <div className="ac-ios-keys">
          {keys.map((key) => (
            <IosKeyRow
              key={String(key.slot) + "-" + String(key.server_id)}
              item={key}
              deletable={used > 1}
              onApply={onApply}
            />
          ))}
        </div>
      )}

      <div className="ac-ios-foot">
        {!ios.blocked && (
          <button
            className="btn btn-outline"
            disabled={busy || !ios.can_add}
            onClick={() => run(api.addIosKey, t("account.iosFailed"))}
          >
            {busy ? t("account.iosAddBusy") : t("account.iosAdd")}
          </button>
        )}
        <Link className="ac-link" to="/guide">
          {t("account.iosGuide")}
        </Link>
      </div>
      {!ios.blocked && (
        <p className="ac-ios-hint">
          {ios.can_add ? t("account.iosAddHint") : t("account.iosLimit", { total })}
        </p>
      )}
    </div>
  );
}

/**
 * Один ключ: ссылка, кнопка копирования и удаление.
 *
 * Сама ссылка показана моноширинной строкой в одну линию. Целиком она
 * длиной в несколько экранов, и читать её незачем — её копируют. Но и
 * прятать совсем нельзя: человек должен видеть, что копирует именно ключ,
 * и отличать один от другого.
 *
 * Удаление спрашивает подтверждение и удаляет насовсем: пароля у ключа нет,
 * и «удалить» здесь ровно для того случая, когда ссылка куда-то уехала.
 * Последний ключ так не снимается — кнопки у него нет, иначе человек одним
 * нажатием остался бы без единого доступа.
 */
function IosKeyRow({ item, deletable, onApply }) {
  const { t, f } = useI18n();
  const [copied, setCopied] = useState(false);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(item.vpn_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Буфера может не быть вовсе (http-контекст, старый вебвью) — тогда
      // ссылку выделяют руками, и сказать об этом честнее, чем соврать
      // галочкой «Скопировано».
      setError(t("account.iosCopyFailed"));
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      onApply(await api.deleteIosKey(item.slot));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.iosDeleteFailed"));
      setBusy(false);
      setAsking(false);
    }
  };

  const meta = item.traffic_bytes
    ? t("account.iosTrafficUsed", { value: f.bytes(item.traffic_bytes) })
    : t("account.iosNeverUsed");

  return (
    <div className="ac-ios-key">
      <div className="ac-ios-key-head">
        <span className="ac-ios-key-name">
          {t("account.iosKeyTitle", { n: item.slot })}
          <span className="ac-ios-key-server">
            {item.country || item.server}
            {item.city ? ", " + item.city : ""}
          </span>
          {item.is_connected && (
            <span className="ac-device-live">
              <span className="ac-device-live-dot" />
              {t("account.iosConnected")}
            </span>
          )}
        </span>
        <button className="ac-ios-copy" onClick={copy}>
          {copied ? t("account.iosCopied") : t("account.iosCopy")}
        </button>
      </div>

      <code className="ac-ios-url">{item.vpn_url}</code>

      <div className="ac-ios-key-foot">
        <span className="ac-ios-key-meta">
          {item.created_at
            ? meta + " · " + t("account.iosCreated", { date: f.shortDate(item.created_at) })
            : meta}
        </span>
        {deletable &&
          (asking ? (
            <span className="ac-device-confirm">
              <button className="ac-device-off" disabled={busy} onClick={remove}>
                {busy ? "…" : t("account.iosDeleteConfirm")}
              </button>
              <button className="ac-link" disabled={busy} onClick={() => setAsking(false)}>
                {t("account.cancel")}
              </button>
            </span>
          ) : (
            <button className="ac-device-off" onClick={() => setAsking(true)}>
              {t("account.iosDelete")}
            </button>
          ))}
      </div>
      {asking && !busy && <p className="ac-ios-warn">{t("account.iosDeleteHint")}</p>}
      {error && <p className="ac-ios-error">{error}</p>}
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

/**
 * Устройство в списке.
 *
 * «Отключить» здесь означает отключить: сервер гасит токен и снимает пира
 * этого устройства с узлов, то есть туннель на нём падает сразу. Поэтому
 * спрашиваем подтверждение — действие видно человеку на другом конце — и
 * поэтому же честно говорим, если узел не ответил и доступ мог остаться.
 */
function DeviceRow({ device, onChanged }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  const unlink = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.unlinkDevice(device.id);
      if (result?.problems?.length) setError(t("account.disconnectPartly"));
      setAsking(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.disconnectFailed"));
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
          {device.is_connected && (
            <span className="ac-device-live">
              <span className="ac-device-live-dot" />
              {t("account.deviceConnected")}
            </span>
          )}
        </span>
        <span className="ac-device-sub">
          {(platform[device.platform] || device.platform || "").toString()}
          {device.is_current
            ? ` · ${t("account.thisDevice")}`
            : ` · ${f.ago(device.last_seen_at)}`}
        </span>
        {error && <span className="ac-device-error">{error}</span>}
      </span>
      {!device.is_current &&
        (asking ? (
          <span className="ac-device-confirm">
            <button className="ac-device-off" disabled={busy} onClick={unlink}>
              {busy ? "…" : t("account.disconnectConfirm")}
            </button>
            <button className="ac-link" disabled={busy} onClick={() => setAsking(false)}>
              {t("account.cancel")}
            </button>
          </span>
        ) : (
          <button className="ac-device-off" onClick={() => setAsking(true)}>
            {t("account.disconnect")}
          </button>
        ))}
    </div>
  );
}

function PlanTab({ data, preselected, onChanged }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [chosen, setChosen] = useState(null);

  /*
  Тариф, выбранный на лендинге.

  Название и цену берём из панели, а не из адреса: в адресе только код, и
  писать рядом с ним цену значит однажды показать здесь одну сумму, а
  выставить счёт на другую. Пока тариф не подгрузился, кнопка продлевает
  текущий — как и раньше.
  */
  useEffect(() => {
    if (!preselected || preselected === data.plan) return;
    let alive = true;
    api
      .plans()
      .then((list) => {
        if (!alive || !Array.isArray(list)) return;
        setChosen(list.find((p) => p.code === preselected && p.purchasable) || null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [preselected, data.plan]);

  const target = chosen ? chosen.code : data.plan;

  const renew = async () => {
    setBusy(true);
    setNotice("");
    try {
      await api.renew(target);
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
          <h2>{chosen ? t("account.switchTitle", { plan: chosen.title }) : t("account.renewTitle")}</h2>
          <p>
            {chosen
              ? t("account.switchText", {
                  term: f.days(chosen.duration_days),
                  price: f.moneyFromKopecks(chosen.price_kopecks, chosen.currency),
                })
              : t("account.renewText", {
                  term: data.period_days
                    ? f.days(data.period_days)
                    : t("account.renewTermFallback"),
                }) + (data.price ? t("account.renewPrice", { price: f.money(data.price) }) : "")}
          </p>
        </div>
        <button className="btn btn-primary ac-renew-btn" disabled={busy} onClick={renew}>
          {busy ? t("account.renewBusy") : chosen ? t("account.switchAction") : t("account.renew")}
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
