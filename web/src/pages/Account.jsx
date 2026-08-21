import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { api, ApiError } from "../lib/api";
import { useDismiss } from "../lib/hooks";
import { SetupGuide } from "../components/SetupGuide.jsx";
import { Picture } from "../components/Picture.jsx";
import { Controls } from "../components/Controls.jsx";
import { PasswordDialog } from "../components/PasswordDialog.jsx";
import { PaymentDialog } from "../components/PaymentDialog.jsx";
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
  // Возврат с платёжной формы приходит с ?order= — человека интересует
  // только одно: прошла ли оплата. Открываем сразу вкладку тарифа.
  const returnOrder = params.get("order") || "";
  const payFailed = params.get("failed") === "1";
  const wantedTab = returnOrder
    ? "plan"
    : TABS.includes(params.get("tab"))
      ? params.get("tab")
      : "account";
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
          <PlanTab
            data={data}
            preselected={wantedPlan}
            returnOrder={returnOrder}
            payFailed={payFailed}
            onChanged={load}
          />
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

      <BypassCard file={data.tunnel_file} guideUrl={data.ios?.guide_url} />

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
                <DeviceRow
                  key={`${d.kind || "app"}-${d.id}`}
                  device={d}
                  onChanged={onChanged}
                  onApply={onApply}
                />
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
 * Файл обхода российских сервисов.
 *
 * Нужен только на iPhone: там подключаются официальным AmneziaVPN, а он про
 * наш список ничего не знает. В наших приложениях для Windows, Android и
 * macOS раздельное туннелирование встроено и работает само.
 *
 * Кнопка гаснет, когда файла нет, а не исчезает: пропавшая кнопка выглядит
 * как поломка интерфейса, погашенная — как «сейчас нечего скачивать», что и
 * происходит на самом деле.
 */
function BypassCard({ file, guideUrl }) {
  const { t, f } = useI18n();
  const ready = file?.available;

  return (
    <div className="ac-card ac-bypass">
      <div className="ac-bypass-body">
        <h2>{t("account.bypassTitle")}</h2>
        <p className="ac-empty">{t("account.bypassText")}</p>
        <span className="ac-key-sub">
          {ready && file.updated_at
            ? t("account.bypassUpdated", { date: f.longDate(file.updated_at) }) +
              (file.size_bytes ? ` · ${f.bytes(file.size_bytes)}` : "")
            : t("account.bypassEmpty")}
        </span>
      </div>
      <div className="ac-bypass-actions">
        <a
          className={`btn btn-primary${ready ? "" : " ac-btn-off"}`}
          href={ready ? file.url : undefined}
          download={ready ? file.filename : undefined}
          aria-disabled={ready ? undefined : "true"}
          onClick={(e) => {
            if (!ready) e.preventDefault();
          }}
        >
          {t("account.bypassDownload")}
        </a>
        {guideUrl && (
          <a className="ac-link" href={guideUrl}>
            {t("account.bypassHow")}
          </a>
        )}
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
  // Отключённый ключ — одна строка на номер, даже когда стран несколько:
  // это один iPhone, и включается он целиком.
  const off = (ios?.disconnected_keys || []).filter(
    (key, index, list) => list.findIndex((k) => k.slot === key.slot) === index,
  );

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

      {/* Отключённые ключи. Не пропадают из карточки: ссылка осталась за
          учёткой, и «Включить» вернёт ту же самую — человеку ничего не надо
          переставлять в Amnezia. */}
      {off.length > 0 && (
        <div className="ac-ios-keys">
          {off.map((key) => (
            <IosKeyOffRow
              key={"off-" + String(key.slot)}
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
 * Отключённый ключ: пометка, «Включить» и «Удалить».
 *
 * Ссылку не показываем и не даём копировать — она сейчас не работает, и
 * копия мёртвой ссылки выглядит как поломка. «Включить» возвращает на узел
 * тот же пир: ссылка, вставленная в Amnezia, оживает без переустановки, а
 * после подключения ключ снова появляется в «Подключённых устройствах».
 */
function IosKeyOffRow({ item, deletable, onApply }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const run = async (action, call) => {
    setBusy(action);
    setError("");
    try {
      onApply(await call());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.iosFailed"));
    } finally {
      setBusy("");
    }
  };

  const meta = item.traffic_bytes
    ? t("account.iosTrafficUsed", { value: f.bytes(item.traffic_bytes) })
    : t("account.iosNeverUsed");

  return (
    <div className="ac-ios-key ac-ios-key-off">
      <div className="ac-ios-key-head">
        <span className="ac-ios-key-name">
          {t("account.iosKeyTitle", { n: item.slot })}
          <span className="ac-ios-key-server">
            {item.country || item.server}
            {item.city ? ", " + item.city : ""}
          </span>
          <span className="ac-ios-off-tag">{t("account.iosOffTag")}</span>
        </span>
        <button
          className="ac-ios-copy"
          disabled={busy === "on"}
          onClick={() => run("on", () => api.enableIosKey(item.slot))}
        >
          {busy === "on" ? t("account.iosEnableBusy") : t("account.iosEnable")}
        </button>
      </div>

      <div className="ac-ios-key-foot">
        <span className="ac-ios-key-meta">
          {meta} · {t("account.iosOffHint")}
        </span>
        {deletable && (
          <button
            className="ac-device-off"
            disabled={busy === "del"}
            onClick={() => run("del", () => api.deleteIosKey(item.slot))}
          >
            {busy === "del" ? "…" : t("account.iosDelete")}
          </button>
        )}
      </div>
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
 *
 * Ключ AmneziaVPN (kind === "ios_key") — тоже устройство: он появляется в
 * списке, как только через него пошёл трафик, и занимает место наравне с
 * приложением. Отключается своим маршрутом — токена за ним нет, есть пир,
 * — а ссылка остаётся за учёткой: включить её обратно можно в карточке
 * ключей, и после подключения строка вернётся сюда сама.
 */
function DeviceRow({ device, onChanged, onApply }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const isKey = device.kind === "ios_key";

  const unlink = async () => {
    setBusy(true);
    setError("");
    try {
      if (isKey) {
        // Ответ — кабинет целиком: строка исчезает, а ключ в карточке
        // ключей получает пометку «отключён» одним и тем же ответом.
        onApply(await api.disconnectIosKey(device.slot));
      } else {
        const result = await api.unlinkDevice(device.id);
        if (result?.problems?.length) setError(t("account.disconnectPartly"));
        onChanged();
      }
      setAsking(false);
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
    amnezia: "AmneziaVPN",
    web: t("account.platformWeb"),
  };

  const name = isKey
    ? t("account.iosDeviceName", { n: device.slot })
    : device.name || platform[device.platform] || t("account.deviceFallback");

  return (
    <div className="ac-device">
      <span className="ac-device-body">
        <span className="ac-device-name">
          {name}
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

function PlanTab({ data, preselected, returnOrder, payFailed, onChanged }) {
  const { t, f } = useI18n();
  const [plans, setPlans] = useState(null);
  const [paying, setPaying] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  /*
  Возврат с платёжной формы. Сам по себе он ничего не подтверждает — оплату
  фиксирует только вебхук провайдера, поэтому страница опрашивает статус
  заказа, пока тот не станет paid, и лишь тогда радуется вслух.
  */
  useEffect(() => {
    if (!returnOrder) return undefined;
    if (payFailed) {
      setNotice(t("account.payReturnFailed"));
      return undefined;
    }
    let alive = true;
    let tries = 0;
    setNotice(t("account.payReturnChecking"));
    const tick = async () => {
      tries += 1;
      try {
        const status = await api.orderStatus(returnOrder);
        if (!alive) return;
        if (status.status === "paid") {
          setNotice(t("account.payReturnPaid"));
          onChanged();
          return;
        }
        if (status.status === "failed" || status.status === "expired") {
          setNotice(t("account.payReturnFailed"));
          return;
        }
      } catch {
        // Сеть мигнула — следующая попытка скажет точнее.
      }
      if (alive && tries < 20) {
        setTimeout(tick, 3000);
      } else if (alive) {
        setNotice(t("account.payReturnPending"));
      }
    };
    tick();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returnOrder, payFailed]);

  /*
  Тарифы берём из панели: там их заводят, там правят цены и сроки. Ни одной
  суммы в вёрстке нет — иначе показанная цена однажды разойдётся с той, по
  которой выставлен счёт.
  */
  useEffect(() => {
    let alive = true;
    api
      .plans()
      .then((list) => alive && Array.isArray(list) && setPlans(list.filter((p) => p.purchasable)))
      .catch(() => alive && setPlans([]));
    return () => {
      alive = false;
    };
  }, []);

  /*
  Оплачен тариф или идёт пробный — от этого зависит весь экран.

  Пробный не продаётся (`purchasable: false`), поэтому среди платных его
  нет: не нашли текущий тариф в списке — значит человек на пробном либо без
  подписки вовсе, и ему показываем «Оформить» на каждом тарифе. Оплатившему
  свой тариф предлагаем продлить, а остальные — как переход. Дни при этом
  складываются: сначала дожидаются оставшиеся, потом в полную силу вступает
  новый тариф, — и очередь видна тут же, под сводкой.
  */
  const list = plans || [];
  const current = list.find((plan) => plan.code === data.plan) || null;
  const paid = Boolean(current);
  const upcoming = data.upcoming || [];

  // Тариф, выбранный на лендинге, поднимаем наверх — человек уже сказал, за
  // чем пришёл, и искать его глазами второй раз не должен.
  const ordered = [...list].sort((a, b) => {
    if (a.code === preselected) return -1;
    if (b.code === preselected) return 1;
    return a.duration_days - b.duration_days;
  });

  /*
  Оплата СБП из окна способов: заказ создаёт панель, дальше — платёжная
  форма провайдера. Вернёмся сюда же с ?order= и дождёмся вебхука опросом
  статуса — сам возврат ничего не подтверждает.
  */
  const paySbp = async () => {
    if (!paying || busy) return;
    setBusy(true);
    setNotice("");
    try {
      const order = await api.renew(paying.code);
      if (order && order.redirect_url) {
        window.location.assign(order.redirect_url);
        return;
      }
      setPaying(null);
      setNotice(t("account.renewCreated"));
      onChanged();
    } catch (err) {
      setPaying(null);
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

      {notice && <div className="ac-notice">{notice}</div>}

      {/* Очередь оплаченных периодов: после смены тарифа деньги не пропали —
          новый тариф ждёт, пока дожатся оставшиеся дни текущего. */}
      {upcoming.length > 0 && (
        <div className="ac-card ac-plan-queue">
          <h2>{t("account.planQueueTitle")}</h2>
          {upcoming.map((next, i) => (
            <p className="ac-plan-queue-row" key={i}>
              {t("account.planQueued", {
                plan: next.plan_title || next.plan,
                term: f.days(next.period_days),
                date: f.shortDate(next.starts_at),
              })}
            </p>
          ))}
          <p className="ac-plan-queue-hint">{t("account.planQueueHint")}</p>
        </div>
      )}

      <div className="ac-card ac-plans">
        <div className="ac-card-head">
          <h2>{paid ? t("account.plansTitlePaid") : t("account.plansTitleTrial")}</h2>
        </div>
        <p className="ac-empty">{paid ? t("account.plansHintPaid") : t("account.plansHintTrial")}</p>

        {plans === null ? (
          <p className="ac-empty">{t("account.plansLoading")}</p>
        ) : ordered.length === 0 ? (
          <p className="ac-empty">{t("account.plansEmpty")}</p>
        ) : (
          <div className="ac-plan-grid">
            {ordered.map((plan) => {
              const mine = plan.code === data.plan;
              return (
                <div className={`ac-plan-card${mine ? " ac-plan-mine" : ""}`} key={plan.code}>
                  {mine && <span className="ac-plan-tag">{t("account.planCurrent")}</span>}
                  <span className="ac-plan-name">{plan.title}</span>
                  <span className="ac-plan-cost">
                    {f.moneyFromKopecks(plan.price_kopecks, plan.currency)}
                  </span>
                  <span className="ac-plan-term-l">{f.days(plan.duration_days)}</span>
                  <ul className="ac-plan-limits">
                    <li>
                      {plan.traffic_limit_bytes == null
                        ? t("account.planUnlimited")
                        : f.bytes(plan.traffic_limit_bytes)}
                    </li>
                    <li>{t("units.devices", { count: plan.device_limit })}</li>
                  </ul>
                  <button
                    className={`btn ${mine ? "btn-primary" : "btn-outline"} ac-plan-btn`}
                    type="button"
                    onClick={() => setPaying(plan)}
                  >
                    {!paid
                      ? t("account.planBuy")
                      : mine
                        ? t("account.planRenewBtn")
                        : t("account.planSwitchBtn")}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <PaymentDialog
        open={Boolean(paying)}
        plan={paying}
        busy={busy}
        onSbp={paySbp}
        onClose={() => (busy ? null : setPaying(null))}
      />

      <RecurringCard onChanged={onChanged} />

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

/*
Автопродление. Карточка живёт своей жизнью: своё состояние с сервера, свои
действия. Главной кнопкой вкладки остаётся «Продлить» — здесь всё тише,
действия оформлены контуром, а не заливкой.
*/
function RecurringCard({ onChanged }) {
  const { t, f } = useI18n();
  const [rec, setRec] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [plan, setPlan] = useState("");

  const load = useCallback(async () => {
    try {
      const fresh = await api.recurring();
      setRec(fresh);
      if (fresh.available.length && !fresh.available.some((p) => p.code === plan)) {
        setPlan(fresh.available[0].code);
      }
    } catch {
      setRec({ status: null, available: [] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (rec === null) {
    return (
      <div className="ac-card ac-rec">
        <h2>{t("account.recTitle")}</h2>
        <p className="ac-empty">{t("account.recLoading")}</p>
      </div>
    );
  }

  const interval = (code) => t(code === "year" ? "account.recYear" : "account.recMonth");
  const live = rec.status === "pending" || rec.status === "active" || rec.status === "past_due";

  const connect = async () => {
    setBusy(true);
    setNote("");
    try {
      const fresh = await api.recurringCreate(plan);
      if (fresh.redirect_url) {
        window.location.assign(fresh.redirect_url);
        return;
      }
      setRec(fresh);
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : t("account.recFailed"));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    setNote("");
    try {
      setRec(await api.recurringCancel());
      setNote(t("account.recCancelled"));
      onChanged();
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : t("account.recFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ac-card ac-rec">
      <h2>{t("account.recTitle")}</h2>

      {!live && rec.available.length === 0 && (
        <p className="ac-empty">{t("account.recUnavailable")}</p>
      )}

      {!live && rec.available.length > 0 && (
        <>
          <p className="ac-rec-text">{t("account.recOffer")}</p>
          <div className="ac-rec-row">
            <div className="ac-rec-opts" role="radiogroup" aria-label={t("account.recTitle")}>
              {rec.available.map((p) => (
                <button
                  key={p.code}
                  type="button"
                  role="radio"
                  aria-checked={plan === p.code}
                  className={`ac-rec-opt${plan === p.code ? " on" : ""}`}
                  onClick={() => setPlan(p.code)}
                >
                  <span className="ac-rec-opt-name">{p.title}</span>
                  <span className="ac-rec-opt-price">
                    {f.moneyFromKopecks(p.amount_kopecks, p.currency)} {interval(p.interval)}
                  </span>
                </button>
              ))}
            </div>
            <button className="btn btn-outline ac-rec-btn" disabled={busy} onClick={connect}>
              {busy ? t("account.recConnectBusy") : t("account.recConnect")}
            </button>
          </div>
        </>
      )}

      {rec.status === "pending" && (
        <div className="ac-rec-row">
          <p className="ac-rec-text">{t("account.recPending")}</p>
          <div className="ac-rec-actions">
            {rec.redirect_url && (
              <a className="btn btn-outline ac-rec-btn" href={rec.redirect_url}>
                {t("account.recContinue")}
              </a>
            )}
            <button className="ac-rec-cancel" disabled={busy} onClick={cancel}>
              {busy ? t("account.recCancelBusy") : t("account.recCancel")}
            </button>
          </div>
        </div>
      )}

      {rec.status === "active" && (
        <div className="ac-rec-row">
          <p className="ac-rec-text">
            {t("account.recActive", {
              plan: rec.plan_title,
              price: f.moneyFromKopecks(rec.amount_kopecks, rec.currency),
              interval: interval(rec.interval),
            })}
            {rec.next_charge_at &&
              t("account.recNext", { date: f.shortDate(rec.next_charge_at) })}
          </p>
          <button className="ac-rec-cancel" disabled={busy} onClick={cancel}>
            {busy ? t("account.recCancelBusy") : t("account.recCancel")}
          </button>
        </div>
      )}

      {rec.status === "past_due" && (
        <div className="ac-rec-row">
          <p className="ac-rec-text">{t("account.recPastDue")}</p>
          <button className="ac-rec-cancel" disabled={busy} onClick={cancel}>
            {busy ? t("account.recCancelBusy") : t("account.recCancel")}
          </button>
        </div>
      )}

      {note && <p className="ac-rec-note">{note}</p>}
    </div>
  );
}
