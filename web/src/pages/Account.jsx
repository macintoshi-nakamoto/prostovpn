import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { api, ApiError } from "../lib/api";
import { isTma, tmaHaptic, tmaUser } from "../lib/telegram.js";
import { TgsEmoji } from "../components/TgsEmoji.jsx";
import { useDismiss } from "../lib/hooks";
import { SetupGuide } from "../components/SetupGuide.jsx";
import { Referrals } from "../components/Referrals.jsx";
import { Picture } from "../components/Picture.jsx";
import { Controls } from "../components/Controls.jsx";
import { PasswordDialog } from "../components/PasswordDialog.jsx";
import { PaymentDialog } from "../components/PaymentDialog.jsx";
import { CabinetBottomNav, CabinetNav, useScrolled } from "../components/CabinetNav.jsx";
import { Sheet } from "../components/Sheet.jsx";
import { Flag } from "../components/Flags.jsx";
import { QrCode } from "../components/QrCode.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./account.css";

const TABS = ["account", "plan", "setup", "friends"];

const SECTION_BY_TAB = { account: "", plan: "subscription", setup: "guide", friends: "friends" };
const TAB_BY_SECTION = { subscription: "plan", guide: "setup", friends: "friends" };

const INVOICE_KEY = "prosto_invoice";

const INVOICE_TTL_MS = 30 * 60 * 1000;
const INVOICE_TTL_CRYPTO_MS = 2 * 60 * 60 * 1000;

function readInvoice(login) {
  try {
    const raw = localStorage.getItem(INVOICE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (!value || !value.orderId || !value.savedAt) return null;

    if (!login || value.login !== login) return null;
    const ttl = value.method === "crypto" ? INVOICE_TTL_CRYPTO_MS : INVOICE_TTL_MS;
    if (Date.now() - value.savedAt > ttl) {
      localStorage.removeItem(INVOICE_KEY);
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

function writeInvoice(value, login) {
  try {
    if (!value) localStorage.removeItem(INVOICE_KEY);
    else {
      localStorage.setItem(
        INVOICE_KEY,
        JSON.stringify({ ...value, login, savedAt: Date.now() }),
      );
    }
  } catch {}
}

function sectionPath(tab, search = "") {
  const section = SECTION_BY_TAB[tab] || "";
  return `/account${section ? `/${section}` : ""}${search}`;
}

export function Account() {
  const { t, raw } = useI18n();
  const { signOut, signInTelegram } = useSession();
  const navigate = useNavigate();
  const { section } = useParams();

  const [params] = useSearchParams();

  const returnOrder = params.get("order") || "";
  const payFailed = params.get("failed") === "1";
  const legacyTab = params.get("tab");
  const wantedTab = returnOrder
    ? "plan"
    : TAB_BY_SECTION[section] || (TABS.includes(legacyTab) ? legacyTab : "account");
  const wantedPlan = params.get("plan") || "";
  const [tab, setTab] = useState(wantedTab);

  useEffect(() => {
    const known = section === undefined || TAB_BY_SECTION[section] !== undefined;
    const canonical = SECTION_BY_TAB[wantedTab] || "";
    const current = section || "";
    if (known && current === canonical && !legacyTab) return;

    const keep = new URLSearchParams(params);
    keep.delete("tab");
    const search = keep.toString();
    navigate(sectionPath(wantedTab, search ? `?${search}` : ""), { replace: true });
  }, [section, wantedTab, legacyTab, params.toString(), navigate]);

  useEffect(() => {
    setTab(wantedTab);
  }, [wantedTab]);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const menuRef = useDismiss(menuOpen, () => setMenuOpen(false));

  const scrolled = useScrolled();

  // Аватар из Telegram — только внутри мини-аппа; подпись проверяет сервер,
  // фото — чистая витрина.
  const tgPhoto = isTma() ? tmaUser()?.photo_url : null;

  // Системная кнопка «назад» Telegram: с любой вкладки — на главную.
  useEffect(() => {
    if (!isTma()) return undefined;
    const back = window.Telegram?.WebApp?.BackButton;
    if (!back) return undefined;
    const home = () => navigate(sectionPath("account"));
    if (tab === "account") {
      back.hide();
      return undefined;
    }
    back.onClick(home);
    back.show();
    return () => {
      back.offClick(home);
      back.hide();
    };
  }, [tab, navigate]);

  const load = useCallback(async () => {
    try {
      setData(await api.account());
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate("/login", {
          replace: true,
          state: { from: { pathname: window.location.pathname, search: window.location.search } },
        });
        return;
      }
      setError(t("account.loadError"));
    }
  }, [navigate, t]);

  const apply = useCallback((fresh) => {
    if (fresh) setData(fresh);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
      <header className={`ac-header${scrolled ? " scrolled" : ""}`}>
        <div className="wrap ac-header-in">
          <Link to="/" className="ac-logo">
            <Picture src="/assets/logo-v3.png" alt="PROSTO" />
          </Link>
          <CabinetNav tabs={TABS} tab={tab} hrefOf={sectionPath} />
          <Controls />
          <div className="ac-user" ref={menuRef}>
            <button
              className={`ac-user-btn${menuOpen ? " open" : ""}`}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span className="ac-avatar">
                {tgPhoto ? (
                  <img src={tgPhoto} alt="" referrerPolicy="no-referrer" />
                ) : (
                  (data?.login || "P").slice(0, 1).toUpperCase()
                )}
              </span>
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
            onManage={() => navigate(sectionPath("plan"))}
            onSetup={() => navigate(sectionPath("setup"))}
            onFriends={() => navigate(sectionPath("friends"))}
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
            onApply={apply}
          />
        )}
        {data && tab === "setup" && (
          <>
            {isTma() && (
              <div className="ap ap-setup">
                <div className="ac-card">
                  <div className="ac-card-head">
                    <h2>{t("account.devicesTitle")}</h2>
                  </div>
                  {data.devices.length === 0 ? (
                    <p className="ac-empty">{t("account.devicesEmpty")}</p>
                  ) : (
                    <div className="ac-devices">
                      {data.devices.map((d) => (
                        <DeviceRow
                          key={`${d.kind || "app"}-${d.id}`}
                          device={d}
                          onChanged={load}
                          onApply={apply}
                        />
                      ))}
                    </div>
                  )}
                </div>
                <IosCard
                  ios={data.ios}
                  active={data.active}
                  onApply={apply}
                  onManage={() => navigate(sectionPath("plan"))}
                />
              </div>
            )}
            <SetupGuide login={data.login} />
          </>
        )}

        {data && tab === "friends" && <Referrals />}
      </main>

      <PasswordDialog
        open={pwOpen}
        onClose={() => setPwOpen(false)}
        onDone={async () => {
          setPwOpen(false);

          await signOut();
          if (isTma()) {
            // Личность подтверждает Telegram — перевходим сами, человек
            // остаётся в кабинете и просто видит, что пароль сменился.
            try {
              await signInTelegram();
              await load();
              try {
                window.Telegram?.WebApp?.showAlert?.(t("password.tmaDone"));
              } catch {}
              return;
            } catch {
              // не вышло — честная форма входа
            }
          }
          navigate("/login", { replace: true });
        }}
      />

      <CabinetBottomNav tabs={TABS} tab={tab} hrefOf={sectionPath} />
    </div>
  );
}

const AP_ICONS = {
  shield: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6l7-3z" />
    </svg>
  ),
  plug: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="7" y="3" width="10" height="18" rx="2.5" />
      <path d="M12 9v6M9 12h6" />
    </svg>
  ),
  key: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="14" r="4" />
      <path d="M11 11l8-8M16 4l3 3M13 7l3 3" />
    </svg>
  ),
  file: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 3h8l4 4v14H6V3z" />
      <path d="M14 3v5h4M9 13h6M9 17h6" />
    </svg>
  ),
  gift: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="9" width="16" height="12" rx="2" />
      <path d="M4 13h16M12 9v12M12 9c-3.5 0-4.5-2-4.5-3A1.8 1.8 0 0 1 9.3 4C11 4 12 6.5 12 9zm0 0c3.5 0 4.5-2 4.5-3A1.8 1.8 0 0 0 14.7 4C13 4 12 6.5 12 9z" />
    </svg>
  ),
  person: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="8" r="3.6" />
      <path d="M5 20c1.2-3.4 3.8-5 7-5s5.8 1.6 7 5" />
    </svg>
  ),
  lock: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="11" width="14" height="9" rx="2.5" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  ),
};

function ApRow({ icon, title, sub, value, disabled, onClick, href, download }) {
  const body = (
    <>
      <span className="ap-row-ic">{AP_ICONS[icon]}</span>
      <span className="ap-row-body">
        <span className="ap-row-t">{title}</span>
        {sub && <span className="ap-row-s">{sub}</span>}
      </span>
      {value ? <span className="ap-row-v">{value}</span> : <span className="ap-chev">&rsaquo;</span>}
    </>
  );
  if (href) {
    return (
      <a className="ap-row" href={href} download={download} aria-disabled={disabled || undefined}>
        {body}
      </a>
    );
  }
  return (
    <button
      type="button"
      className="ap-row"
      onClick={onClick}
      aria-disabled={disabled || undefined}
      disabled={disabled}
    >
      {body}
    </button>
  );
}

// Пауза подписки — компактный ряд с фирменным эмодзи. Подтверждение —
// системным диалогом Telegram, снятие паузы — одним тапом.
function TmaFreeze({ freeze, onApply }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!freeze) return null;
  const frozen = Boolean(freeze.frozen);

  const run = async (call) => {
    setBusy(true);
    setError("");
    try {
      onApply(await call());
      tmaHaptic("medium");
    } catch (err) {
      setError(err?.message || t("account.freezeFailed"));
    } finally {
      setBusy(false);
    }
  };

  const askFreeze = () => {
    const wa = window.Telegram?.WebApp;
    const question = t("account.tmaFreezeConfirm");
    try {
      wa.showConfirm(question, (ok) => {
        if (ok) run(api.freeze);
      });
    } catch {
      // старый клиент или не-Telegram: обычный confirm
      if (window.confirm(question)) run(api.freeze);
    }
  };

  const sub = frozen
    ? t("account.tmaFrozenSub", { date: f.shortDate(freeze.frozen_at) })
    : freeze.can_freeze
      ? t("account.tmaFreezeSub")
      : freeze.reason || "";

  return (
    <div className="ap-freeze">
      <TgsEmoji name="freeze-emoji" size={48} />
      <span className="ap-row-body">
        <span className="ap-row-t">{t("account.tmaFreezeTitle")}</span>
        {sub && <span className="ap-row-s">{sub}</span>}
        {error && <span className="ap-freeze-err">{error}</span>}
      </span>
      {(frozen || freeze.can_freeze) && (
        <button
          type="button"
          className="ap-freeze-btn"
          disabled={busy}
          onClick={frozen ? () => run(api.resume) : askFreeze}
        >
          {busy ? "…" : frozen ? t("account.tmaResumeBtn") : t("account.tmaFreezeBtn")}
        </button>
      )}
    </div>
  );
}

// Главная мини-аппа: карта статуса с круглой CTA, пауза, действия и
// аккаунт — группами строк. Стиль нативных мини-аппов, наш цвет.
function TmaHome({ data, used, onManage, onSetup, onFriends, onPassword, onChanged, onApply }) {
  const { t, f } = useI18n();
  const frozen = Boolean(data.freeze?.frozen);
  const file = data.tunnel_file;
  const [copied, setCopied] = useState(false);

  // Иерархия карты: статус — точкой и словом, дни — крупной цифрой,
  // тариф — чипом, точная дата — мелко. Никаких предложений из данных.
  const status = frozen
    ? t("account.tmaStatusFrozen")
    : data.active
      ? t("account.tmaStatusOn")
      : t("account.tmaStatusOff");

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(data.public_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  return (
    <div className="ap">
      <div className="ap-card">
        <div className="ap-head">
          <span className="ap-ic ap-ic-emoji">
            <TgsEmoji name="fire" size={62} />
          </span>
          <span className="ap-head-body">
            <span className="ap-title-row">
              <span className="ap-title">Prosto VPN</span>
              {data.plan_title && <span className="ap-chip">{data.plan_title}</span>}
            </span>
            <span className="ap-status">
              <span
                className={`ap-dot${frozen ? " is-frozen" : data.active ? " is-on" : " is-off"}`}
              />
              {status}
            </span>
          </span>
        </div>
        {(data.active || frozen) && data.days_left != null ? (
          <div className="ap-days">
            <span className="ap-days-n">{f.days(data.days_left)}</span>
            {data.expires_at && (
              <span className="ap-days-d">
                {t("account.tmaUntil", { date: f.longDate(data.expires_at) })}
              </span>
            )}
          </div>
        ) : (
          !data.active && !frozen && <p className="ap-sub">{t("account.subscribePrompt")}</p>
        )}
        <button className="ap-cta" onClick={onManage}>
          {t("account.manage")}
        </button>
        <div className="ap-mini">
          <span>
            {t("account.statDevices")}{" "}
            <b>{t("account.statOf", { used, total: data.device_limit })}</b>
          </span>
          <span>
            {t("account.statTraffic")} <b>{f.bytes(data.traffic_used_bytes)}</b>
          </span>
        </div>
      </div>

      <TmaFreeze freeze={data.freeze} onApply={onApply} />

      <div className="ap-rows">
        <ApRow
          icon="plug"
          title={t("account.devicesAdd")}
          sub={t("account.tmaConnectSub")}
          onClick={onSetup}
        />
        <ApRow
          icon="key"
          title={t("account.tmaIosTitle")}
          sub={t("account.tmaIosSub")}
          onClick={onSetup}
        />
        <ApRow
          icon="file"
          title={t("account.bypassTitle")}
          sub={t("account.tmaBypassSub")}
          href={file?.available ? file.url : undefined}
          download={file?.available ? file.filename : undefined}
          disabled={!file?.available}
        />
        <ApRow
          icon="gift"
          title={t("account.tmaRefTitle")}
          sub={t("account.tmaRefSub")}
          onClick={onFriends}
        />
      </div>

      <div className="ap-rows">
        <ApRow icon="person" title={t("account.fieldLogin")} value={data.login} onClick={copyId} />
        <ApRow icon="lock" title={t("account.changePassword")} onClick={onPassword} />
        <ApRow
          icon="file"
          title={t("account.statPublicId")}
          value={copied ? t("account.tmaCopied") : data.public_id}
          onClick={copyId}
        />
      </div>

      <div className="ac-card">
        <div className="ac-kvs">
          <EmailRow email={data.email} onChanged={onChanged} />
        </div>
      </div>
    </div>
  );
}

function AccountTab({ data, onManage, onSetup, onFriends, onPassword, onChanged, onApply }) {
  const { t, f } = useI18n();
  const used = data.devices.length;
  const free = Math.max(0, data.device_limit - used);

  if (isTma()) {
    return (
      <TmaHome
        data={data}
        used={used}
        onManage={onManage}
        onSetup={onSetup}
        onFriends={onFriends}
        onPassword={onPassword}
        onChanged={onChanged}
        onApply={onApply}
      />
    );
  }

  return (
    <div className="ac-account">
      <div className={`ac-hero${data.freeze?.frozen ? " frozen" : ""}`}>
        <div className="ac-hero-body">
          <span className="ac-hero-status">
            <span className="ac-dot" />
            {data.freeze?.frozen
              ? t("account.frozen")
              : data.active
                ? t("account.active")
                : t("account.inactive")}
          </span>
          <span className="ac-hero-plan">
            {data.plan_title ? `Prosto VPN · ${data.plan_title}` : t("account.noPlan")}
          </span>
          <span className="ac-hero-sub">
            {data.freeze?.frozen
              ? t("account.frozenHero", { days: f.days(data.days_left ?? 0) })
              : data.expires_at
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

function IosCard({ ios, active, onApply, onManage }) {
  const { t } = useI18n();

  const keys = ios?.keys || [];
  const total = ios?.max_keys || 5;
  const used = ios?.keys_count || 0;

  const off = (ios?.disconnected_keys || []).filter(
    (key, index, list) => list.findIndex((k) => k.slot === key.slot) === index,
  );

  const devices = [];
  for (const key of keys) {
    const found = devices.find((d) => d.slot === key.slot);
    if (found) found.links.push(key);
    else devices.push({ slot: key.slot, links: [key] });
  }

  const servers = ios?.servers || [];
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState(null);
  const [creating, setCreating] = useState(false);
  const [pickError, setPickError] = useState("");

  const openPicker = () => {
    setPickError("");
    setPicked(servers.length ? servers[0].id : null);
    setPicking(true);
  };

  const create = async () => {
    setCreating(true);
    setPickError("");
    try {
      onApply(ios?.available ? await api.addIosKey(picked) : await api.enableIos(picked));
      setPicking(false);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setPickError(
        code === "no_subscription"
          ? t("account.iosNoSubscription")
          : err instanceof ApiError
            ? err.message
            : t("account.iosFailed"),
      );
    } finally {
      setCreating(false);
    }
  };

  const picker = (
    <IosPicker
      open={picking}
      servers={servers}
      picked={picked}
      busy={creating}
      error={pickError}
      total={total}
      onPick={setPicked}
      onCreate={create}
      onClose={() => (creating ? null : setPicking(false))}
    />
  );

  if (!ios?.available) {
    return (
      <div className="ac-card ac-ios">
        <div className="ac-card-head">
          <h2>{t("account.iosTitle")}</h2>
        </div>
        <p className="ac-empty">{t("account.iosOffer")}</p>
        <div className="ac-ios-foot">
          {active ? (
            <button className="btn btn-primary" onClick={openPicker}>
              {t("account.iosGet")}
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
        {picker}
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

      {devices.length > 0 && (
        <div className="ac-ios-keys">
          {devices.map((device) => (
            <IosKeyRow
              key={"slot-" + String(device.slot)}
              item={device.links[0]}
              links={device.links}
              deletable={used > 1}
              onApply={onApply}
            />
          ))}
        </div>
      )}

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
          <button className="btn btn-outline" disabled={!ios.can_add} onClick={openPicker}>
            {t("account.iosAdd")}
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
      {picker}
    </div>
  );
}

function IosPicker({ open, servers, picked, busy, error, total, onPick, onCreate, onClose }) {
  const { t } = useI18n();

  return (
    <Sheet
      open={open}
      title={t("account.iosPickTitle")}
      sub={t("account.iosPickSub")}
      onClose={onClose}
    >
      {servers.length > 0 ? (
        <div className="sheet-list">
          {servers.map((server, index) => (
            <button
              key={server.id}
              type="button"
              className={"sheet-item" + (picked === server.id ? " is-picked" : "")}
              disabled={busy}
              aria-pressed={picked === server.id}
              data-autofocus={index === 0 ? "" : undefined}
              onClick={() => onPick(server.id)}
            >
              <Flag code={server.country_code} title={server.country || server.name} />
              <span className="sheet-item-body">
                <span className="sheet-item-name">{server.country || server.name}</span>
                {server.city && <span className="sheet-item-sub">{server.city}</span>}
              </span>
              <span className="sheet-item-mark" aria-hidden="true">
                ✓
              </span>
            </button>
          ))}
        </div>
      ) : (

        <p className="sheet-note">{t("account.iosPickEmpty")}</p>
      )}

      {error && <p className="sheet-error">{error}</p>}

      <div className="sheet-foot">
        <button className="btn btn-primary" disabled={busy} onClick={onCreate}>
          {busy ? t("account.iosPickBusy") : t("account.iosPickCreate")}
        </button>
        <p className="sheet-note">{t("account.iosPickNote", { total })}</p>
      </div>
    </Sheet>
  );
}

function IosKeyRow({ item, links, deletable, onApply }) {
  const { t, f } = useI18n();
  const [copied, setCopied] = useState(0);
  const [asking, setAsking] = useState(false);

  const [qr, setQr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const rows = links && links.length ? links : [item];

  const copy = async (link) => {
    try {
      await navigator.clipboard.writeText(link.vpn_url);
      setCopied(link.server_id);
      setTimeout(() => setCopied(0), 1600);
    } catch {
      setError(t("account.iosCopyFailed"));
    }
  };

  const run = async (call) => {
    setBusy(true);
    setError("");
    try {
      onApply(await call());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.iosDeleteFailed"));
      setBusy(false);
      setAsking(false);
    }
  };

  const traffic = rows.reduce((sum, link) => sum + (link.traffic_bytes || 0), 0);
  const meta = traffic
    ? t("account.iosTrafficUsed", { value: f.bytes(traffic) })
    : t("account.iosNeverUsed");
  const live = rows.some((link) => link.is_connected);

  return (
    <div className="ac-ios-key">
      <div className="ac-ios-key-head">
        <span className="ac-ios-key-name">
          {t("account.iosKeyTitle", { n: item.slot })}
          {live && (
            <span className="ac-device-live">
              <span className="ac-device-live-dot" />
              {t("account.iosConnected")}
            </span>
          )}
        </span>
      </div>

      {rows.map((link) => (
        <div className="ac-ios-link" key={link.server_id}>
          <div className="ac-ios-link-head">
            <span className="ac-ios-key-server">
              {link.country || link.server}
              {link.city ? ", " + link.city : ""}
            </span>
            <span className="ac-ios-link-acts">
              <button className="ac-ios-copy" onClick={() => copy(link)}>
                {copied === link.server_id ? t("account.iosCopied") : t("account.iosCopy")}
              </button>
              {link.qr_payload && (
                <button className="ac-ios-qr-btn" onClick={() => setQr(link)}>
                  {t("account.iosQr")}
                </button>
              )}
            </span>
          </div>
          <code className="ac-ios-url">{link.vpn_url}</code>
        </div>
      ))}

      <div className="ac-ios-key-foot">
        <span className="ac-ios-key-meta">
          {item.created_at
            ? meta + " · " + t("account.iosCreated", { date: f.shortDate(item.created_at) })
            : meta}
        </span>

        <button className="ac-device-off" onClick={() => setAsking(true)}>
          {deletable ? t("account.iosDelete") : t("account.disconnect")}
        </button>
      </div>
      {error && <p className="ac-ios-error">{error}</p>}

      <Sheet
        open={qr !== null}
        title={t("account.iosQrTitle", { n: item.slot })}
        sub={t("account.iosQrSub", {
          country: (qr && (qr.country || qr.server)) || "",
        })}
        onClose={() => setQr(null)}
      >
        {qr && (
          <>
            <div className="ac-qr-plate">
              <QrCode
                value={qr.qr_payload}
                label={t("account.iosQrTitle", { n: item.slot })}
                fallback={<p className="sheet-error">{t("account.iosQrFailed")}</p>}
              />
            </div>
            <p className="sheet-note">{t("account.iosQrHint")}</p>
          </>
        )}
      </Sheet>

      <Sheet
        open={asking}
        title={t(deletable ? "account.iosDeleteTitle" : "account.iosDisconnectTitle", {
          n: item.slot,
        })}
        sub={deletable ? t("account.iosDeleteHint") : t("account.iosDisconnectHint")}
        onClose={() => (busy ? null : setAsking(false))}
      >
        <div className="sheet-foot">
          <button
            className={"btn btn-primary" + (deletable ? " sheet-danger" : "")}
            data-autofocus=""
            disabled={busy}
            onClick={() =>
              run(() =>
                deletable ? api.deleteIosKey(item.slot) : api.disconnectIosKey(item.slot),
              )
            }
          >
            {busy ? "…" : deletable ? t("account.iosDelete") : t("account.disconnect")}
          </button>
          <button className="btn btn-outline" disabled={busy} onClick={() => setAsking(false)}>
            {t("account.cancel")}
          </button>
        </div>
      </Sheet>
    </div>
  );
}

function IosKeyOffRow({ item, deletable, onApply }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);

  const run = async (action, call) => {
    setBusy(action);
    setError("");
    try {
      onApply(await call());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.iosFailed"));
      setAsking(false);
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
          <button className="ac-device-off" onClick={() => setAsking(true)}>
            {t("account.iosDelete")}
          </button>
        )}
      </div>
      {error && <p className="ac-ios-error">{error}</p>}

      <Sheet
        open={asking}
        title={t("account.iosDeleteTitle", { n: item.slot })}
        sub={t("account.iosDeleteHint")}
        onClose={() => (busy === "del" ? null : setAsking(false))}
      >
        <div className="sheet-foot">
          <button
            className="btn btn-primary sheet-danger"
            data-autofocus=""
            disabled={busy === "del"}
            onClick={() => run("del", () => api.deleteIosKey(item.slot))}
          >
            {busy === "del" ? "…" : t("account.iosDelete")}
          </button>
          <button
            className="btn btn-outline"
            disabled={busy === "del"}
            onClick={() => setAsking(false)}
          >
            {t("account.cancel")}
          </button>
        </div>
      </Sheet>
    </div>
  );
}

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

function isDaily(plan) {
  return Boolean(plan) && plan.duration_days === 1;
}

function FreezeCard({ freeze, onApply }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);

  if (!freeze) return null;

  const frozen = !!freeze.frozen;

  // Карточка видна всем и всегда, даже когда пауза недоступна: спрятанная
  // возможность — это возможность, о которой не знают. Кнопка при этом
  // выключена, а под ней стоит причина отказа — так человек понимает, что
  // нужно сделать, чтобы пауза стала доступна.

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      onApply(await action());
      setAsking(false);
    } catch (err) {
      setError(err?.message || t("account.freezeFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`ac-card ac-freeze${frozen ? " ac-freeze-on" : ""}`}>
      <Picture
        src="/assets/freeze.png"
        alt=""
        className="ac-freeze-art"
        imgClassName="ac-freeze-img"
      />

      <div className="ac-freeze-body">
        <h2>{frozen ? t("account.freezeOnTitle") : t("account.freezeTitle")}</h2>

        <p className="ac-freeze-text">
          {frozen
            ? t("account.freezeOnText", {
                days: f.days(freeze.days_left ?? 0),
                since: freeze.frozen_at ? f.shortDate(freeze.frozen_at) : "",
              })
            : t("account.freezeText")}
        </p>

        {frozen && freeze.frozen_days > 0 && (
          <p className="ac-freeze-meta">
            {t("account.freezeElapsed", { days: f.days(freeze.frozen_days) })}
          </p>
        )}

        {!frozen && freeze.used_days > 0 && (
          <p className="ac-freeze-meta">
            {t("account.freezeUsed", { days: f.days(freeze.used_days) })}
          </p>
        )}

        {!frozen && !freeze.can_freeze && freeze.reason && (
          <p className="ac-freeze-meta">{freeze.reason}</p>
        )}

        {error && <p className="ac-freeze-error">{error}</p>}

        {frozen ? (
          <button
            className="ac-freeze-btn"
            type="button"
            disabled={busy}
            onClick={() => run(api.resume)}
          >
            {busy ? t("account.freezeBusy") : t("account.freezeResume")}
          </button>
        ) : asking ? (
          <div className="ac-freeze-ask">
            <p className="ac-freeze-text">{t("account.freezeConfirm")}</p>
            <div className="ac-freeze-row">
              <button
                className="ac-freeze-btn"
                type="button"
                disabled={busy}
                onClick={() => run(api.freeze)}
              >
                {busy ? t("account.freezeBusy") : t("account.freezeConfirmYes")}
              </button>
              <button
                className="ac-freeze-cancel"
                type="button"
                disabled={busy}
                onClick={() => setAsking(false)}
              >
                {t("account.freezeConfirmNo")}
              </button>
            </div>
          </div>
        ) : (
          <button
            className="ac-freeze-btn"
            type="button"
            disabled={!freeze.can_freeze}
            onClick={() => setAsking(true)}
          >
            {t("account.freezeAction")}
          </button>
        )}
      </div>
    </div>
  );
}

function PlanTab({ data, preselected, returnOrder, payFailed, onChanged, onApply }) {
  const { t, f } = useI18n();
  const [plans, setPlans] = useState(null);
  const [paying, setPaying] = useState(null);

  const [busyMethod, setBusyMethod] = useState(null);
  const [notice, setNotice] = useState("");

  const noticeRef = useRef(null);
  useEffect(() => {
    if (!notice || !noticeRef.current) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    noticeRef.current.scrollIntoView({
      behavior: still ? "auto" : "smooth",
      block: "center",
    });
  }, [notice]);

  const [dailyDays, setDailyDays] = useState(7);

  const [invoice, setInvoiceState] = useState(() => readInvoice(data.login));
  const setInvoice = useCallback(
    (next) => {
      setInvoiceState((prev) => {
        const value = typeof next === "function" ? next(prev) : next;
        writeInvoice(value, data.login);
        return value;
      });
    },
    [data.login],
  );

  useEffect(() => {
    if (!returnOrder) return undefined;
    if (payFailed) {
      setNotice(t("account.payReturnFailed"));
      return undefined;
    }
    let alive = true;
    let timer = 0;
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
      } catch {}

      const crypto = readInvoice(data.login);
      const isCrypto = crypto && crypto.orderId === returnOrder && crypto.method === "crypto";
      if (alive && tries < (isCrypto ? 60 : 20)) {
        timer = setTimeout(tick, 3000);
      } else if (alive) {
        setNotice(t(isCrypto ? "account.payReturnPendingCrypto" : "account.payReturnPending"));
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [returnOrder, payFailed]);

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

  const list = plans || [];
  const current = list.find((plan) => plan.code === data.plan) || null;
  const paid = Boolean(current);
  const upcoming = data.upcoming || [];

  const ordered = [...list].sort((a, b) => {
    if (a.code === preselected) return -1;
    if (b.code === preselected) return 1;
    return a.duration_days - b.duration_days;
  });

  useEffect(() => {
    if (!invoice || invoice.status !== "pending" || paying || !plans) return;
    const plan = plans.find((p) => p.code === invoice.planCode);
    if (plan) {
      setPaying(plan);

      if (invoice.quantity) setDailyDays(invoice.quantity);
    }
  }, [invoice && invoice.orderId, invoice && invoice.status, plans]);

  const payWith = async (method) => {
    if (!paying || busyMethod) return;
    const days = isDaily(paying) ? dailyDays : 1;
    const win = window.open("about:blank", "_blank");
    setBusyMethod(method);
    setNotice("");
    try {
      const order = await api.renew(paying.code, days, method);
      if (order && order.redirect_url) {
        if (win) {
          try {
            win.opener = null;
          } catch {}
          win.location = order.redirect_url;
        }
        setInvoice({
          planCode: paying.code,
          orderId: order.id,
          url: order.redirect_url,
          quantity: days,
          status: "pending",

          method: order.payment_method || method,
        });
        return;
      }
      if (win) win.close();
      setPaying(null);
      setNotice(t("account.renewCreated"));
      onChanged();
    } catch (err) {
      if (win) win.close();
      setPaying(null);
      setNotice(err instanceof ApiError ? err.message : t("account.renewFailed"));
    } finally {
      setBusyMethod(null);
    }
  };

  useEffect(() => {
    if (!invoice || invoice.status !== "pending") return undefined;
    let alive = true;
    let timer = 0;
    let tries = 0;
    const finish = (status) => {
      setInvoice((inv) =>
        inv && inv.orderId === invoice.orderId ? { ...inv, status } : inv,
      );
    };
    const tick = async () => {
      tries += 1;
      try {
        const status = await api.orderStatus(invoice.orderId);
        if (!alive) return;
        if (status.status === "paid") {
          finish("paid");
          onChanged();
          return;
        }
        if (status.status === "failed" || status.status === "expired") {
          finish("failed");
          return;
        }
      } catch {}

      const limit = invoice.method === "crypto" ? 2400 : 600;
      if (alive && tries < limit) timer = setTimeout(tick, 3000);
    };
    timer = setTimeout(tick, 3000);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [invoice && invoice.orderId, invoice && invoice.status]);

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
          <span className="ac-plan-l">
            {t(data.freeze?.frozen ? "account.planUntilPaused" : "account.planUntil")}
          </span>
          <span className="ac-plan-v">{data.expires_at ? f.shortDate(data.expires_at) : "—"}</span>
        </div>
        <div>
          <span className="ac-plan-l">{t("account.planLeft")}</span>
          <span className="ac-plan-v ac-accent">
            {data.days_left != null ? f.days(data.days_left) : "—"}
          </span>
        </div>
      </div>

      {notice && (
        <div className="ac-notice" role="alert" ref={noticeRef}>
          {notice}
        </div>
      )}

      {!isTma() && <FreezeCard freeze={data.freeze} onApply={onApply} />}

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
                    {f.moneyFromKopecks(
                      plan.price_kopecks * (isDaily(plan) ? dailyDays : 1),
                      plan.currency,
                    )}
                  </span>
                  <span className="ac-plan-term-l">
                    {isDaily(plan)
                      ? t("account.dailyFor", { days: f.days(dailyDays) })
                      : f.days(plan.duration_days)}
                  </span>
                  {isDaily(plan) && (
                    <div className="ac-daily">
                      <button
                        type="button"
                        className="ac-daily-btn"
                        aria-label={t("account.dailyLess")}
                        disabled={dailyDays <= 1}
                        onClick={() => setDailyDays((n) => Math.max(1, n - 1))}
                      >
                        −
                      </button>
                      <input
                        className="ac-daily-input"
                        inputMode="numeric"
                        value={dailyDays}
                        aria-label={t("account.dailyLabel")}
                        onChange={(e) => {
                          const digits = e.target.value.replace(/\D/g, "").slice(0, 2);
                          setDailyDays(digits ? Math.min(90, Number(digits)) : "");
                        }}
                        onBlur={() => setDailyDays((n) => (n >= 1 ? n : 1))}
                      />
                      <button
                        type="button"
                        className="ac-daily-btn"
                        aria-label={t("account.dailyMore")}
                        disabled={dailyDays >= 90}
                        onClick={() => setDailyDays((n) => Math.min(90, (Number(n) || 0) + 1))}
                      >
                        +
                      </button>
                    </div>
                  )}
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
                    onClick={() => {
                      if (invoice && invoice.planCode === plan.code && invoice.status !== "pending") {
                        setInvoice(null);
                      }
                      setPaying(plan);
                    }}
                    disabled={isDaily(plan) && !(Number(dailyDays) >= 1)}
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

        quantity={
          invoice && invoice.planCode === (paying && paying.code) && invoice.status === "pending"
            ? invoice.quantity || 1
            : isDaily(paying)
              ? Number(dailyDays) || 1
              : 1
        }
        busyMethod={busyMethod}
        invoice={paying && invoice && invoice.planCode === paying.code ? invoice : null}
        onPay={payWith}
        onNewInvoice={() => setInvoice(null)}
        onClose={() => (busyMethod ? null : setPaying(null))}
      />

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

      <TransferCard data={data} onChanged={onChanged} />

      <RecurringControl onChanged={onChanged} />
    </div>
  );
}

function TransferCard({ data, onChanged }) {
  const { t, f } = useI18n();
  const [recipient, setRecipient] = useState("");
  const [days, setDays] = useState(1);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [history, setHistory] = useState([]);

  const load = useCallback(async () => {
    try {
      setHistory(await api.transfers());
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const left = data.days_left || 0;
  const amount = Number(days) || 0;
  const ready = recipient.trim().length > 0 && amount >= 1 && amount <= left;

  const send = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setNote("");
    try {
      await api.transferDays(recipient.trim(), amount);
      setNote(t("account.trSent", { days: f.days(amount) }));
      setRecipient("");
      setDays(1);
      onChanged();
      load();
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : t("account.trFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ac-card ac-transfer">
      <h2>{t("account.trTitle")}</h2>
      <p className="ac-empty">{t("account.trHint", { left: f.days(left) })}</p>

      <div className="ac-tr-form">
        <input
          className="ac-tr-input"
          placeholder={t("account.trWho")}
          aria-label={t("account.trWho")}
          value={recipient}
          onChange={(e) => setRecipient(e.target.value)}
        />
        <input
          className="ac-tr-days"
          inputMode="numeric"
          aria-label={t("account.trDays")}
          value={days}
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, "").slice(0, 4);
            setDays(digits ? Number(digits) : "");
          }}
          onBlur={() => setDays((n) => (Number(n) >= 1 ? Number(n) : 1))}
        />
        <button className="btn btn-outline ac-tr-btn" disabled={!ready || busy} onClick={send}>
          {busy ? t("account.trBusy") : t("account.trSend")}
        </button>
      </div>

      {amount > left && left > 0 && <p className="ac-tr-warn">{t("account.trTooMany")}</p>}
      {note && <p className="ac-rec-note">{note}</p>}

      {history.length > 0 && (
        <div className="ac-tr-list">
          {history.map((row) => (
            <div className="ac-tr-row" key={row.id}>
              <span className={row.direction === "sent" ? "ac-tr-out" : "ac-tr-in"}>
                {row.direction === "sent" ? "−" : "+"}
                {f.days(row.days)}
              </span>
              <span className="ac-tr-who">
                {t(row.direction === "sent" ? "account.trTo" : "account.trFrom", {
                  who: row.counterpart,
                })}
              </span>
              <span className="ac-tr-when">{f.shortDate(row.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RecurringControl({ onChanged }) {
  const { t, f } = useI18n();
  const [rec, setRec] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [plan, setPlan] = useState("");

  const load = useCallback(async () => {
    try {
      const fresh = await api.recurring();
      setRec(fresh);
      setPlan((prev) =>
        fresh.available.some((p) => p.code === prev) ? prev : fresh.available[0]?.code || "",
      );
    } catch {
      setRec((prev) => prev || { status: null, available: [] });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!open) return undefined;
    setNote("");
    load();
    return undefined;
  }, [open, load]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy]);

  useEffect(() => {
    if (!open || !rec || rec.status !== "pending") return undefined;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [open, rec, load]);

  const interval = (code) => t(code === "year" ? "account.recYear" : "account.recMonth");

  const connect = async () => {
    if (busy || !plan) return;

    const win = window.open("about:blank", "_blank");
    setBusy(true);
    setNote("");
    try {
      const fresh = await api.recurringCreate(plan);
      if (fresh.redirect_url && win) {
        try {
          win.opener = null;
        } catch {}
        win.location = fresh.redirect_url;
      } else if (win) {
        win.close();
      }
      setRec(fresh);
    } catch (err) {
      if (win) win.close();
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

  if (rec === null) return null;

  const live = rec.status === "pending" || rec.status === "active" || rec.status === "past_due";

  if (!live) return null;
  const label =
    rec.status === "active"
      ? t("account.recLineOn", {
          price: f.moneyFromKopecks(rec.amount_kopecks, rec.currency),
          interval: interval(rec.interval),
        })
      : rec.status === "pending"
        ? t("account.recLinePending")
        : rec.status === "past_due"
          ? t("account.recLineDue")
          : rec.available.length
            ? t("account.recLineOff")
            : null;
  if (!label) return null;

  return (
    <>
      <p className="ac-rec-line">
        <button
          type="button"
          className={`ac-rec-line-btn${rec.status === "past_due" ? " warn" : ""}`}
          onClick={() => setOpen(true)}
        >
          {label}
        </button>
      </p>

      {open && (
        <div className="pay-overlay" onMouseDown={() => (busy ? null : setOpen(false))}>
          <div
            className="pay"
            role="dialog"
            aria-modal="true"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <button
              className="pay-close"
              type="button"
              onClick={() => (busy ? null : setOpen(false))}
              aria-label={t("account.recClose")}
            >
              ✕
            </button>

            <div className="pay-head">
              <span className="pay-plan">{t("account.recTitle")}</span>
              {rec.status === "active" && (
                <>
                  <span className="pay-sum">
                    {f.moneyFromKopecks(rec.amount_kopecks, rec.currency)}
                  </span>
                  <span className="pay-term">
                    {rec.plan_title} · {interval(rec.interval)}
                  </span>
                </>
              )}
            </div>

            {!live && rec.available.length > 0 && (
              <>
                <p className="ac-rec-text">{t("account.recOffer")}</p>
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
                <button
                  className="btn btn-primary pay-inv-btn"
                  type="button"
                  disabled={busy}
                  onClick={connect}
                >
                  {busy ? t("account.recConnectBusy") : t("account.recConnect")}
                </button>
              </>
            )}

            {rec.status === "pending" && (
              <div className="pay-invoice">
                <span className="pay-inv-pulse" aria-hidden="true" />
                <p className="pay-inv-title">{t("account.recPendTitle")}</p>
                <p className="pay-inv-sub">{t("account.recPending")}</p>
                {rec.redirect_url && (
                  <a
                    className="btn btn-primary pay-inv-btn"
                    href={rec.redirect_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("account.recContinue")}
                  </a>
                )}
                <button className="ac-rec-cancel" type="button" disabled={busy} onClick={cancel}>
                  {busy ? t("account.recCancelBusy") : t("account.recCancelPending")}
                </button>
              </div>
            )}

            {rec.status === "active" && (
              <div className="ac-rec-modal-body">
                <p className="ac-rec-text">
                  {rec.next_charge_at
                    ? t("account.recNextFull", { date: f.shortDate(rec.next_charge_at) })
                    : t("account.recActiveNote")}
                </p>
                <button className="ac-rec-cancel" type="button" disabled={busy} onClick={cancel}>
                  {busy ? t("account.recCancelBusy") : t("account.recCancel")}
                </button>
              </div>
            )}

            {rec.status === "past_due" && (
              <div className="ac-rec-modal-body">
                <p className="ac-rec-text">{t("account.recPastDue")}</p>
                <button className="ac-rec-cancel" type="button" disabled={busy} onClick={cancel}>
                  {busy ? t("account.recCancelBusy") : t("account.recCancel")}
                </button>
              </div>
            )}

            {note && <p className="ac-rec-note">{note}</p>}
          </div>
        </div>
      )}
    </>
  );
}
