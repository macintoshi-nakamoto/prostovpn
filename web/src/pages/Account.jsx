import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { api, ApiError } from "../lib/api";
import { isTma, tmaHaptic, tmaOpenApp, tmaOpenLink, tmaUser, tmaAlert } from "../lib/telegram.js";
import { EmailDialog } from "../components/EmailDialog.jsx";
import { SheetShell } from "../components/SheetShell.jsx";
import { ScreenShell } from "../components/ScreenShell.jsx";
import { CryptoIcon, SbpIcon, TelegramIcon, TonIcon } from "../components/PayIcons.jsx";
import { starsPayUrl } from "../lib/contacts.js";
import { TgsEmoji } from "../components/TgsEmoji.jsx";
import { SetupGuide } from "../components/SetupGuide.jsx";
import { AppsScreen } from "../components/AppsScreen.jsx";
import { ServerStatus } from "../components/ServerStatus.jsx";
import { TmaExternalKeys } from "../components/TmaExternalKeys.jsx";
import { TmaDevicesSheet } from "../components/TmaDevicesSheet.jsx";
import { AppStoreSheet, appStoreAutoAllowed, markAppStoreShown } from "../components/AppStoreSheet.jsx";
import { Referrals } from "../components/Referrals.jsx";
import { Picture } from "../components/Picture.jsx";
import { PasswordDialog } from "../components/PasswordDialog.jsx";
import { PaymentDialog } from "../components/PaymentDialog.jsx";
import { CabinetBottomNav, CabinetNav } from "../components/CabinetNav.jsx";
import { ProfileTab, WalletSheet } from "../components/Profile.jsx";
import { ensureConnected, shortAddress, tonAddress, tonPay, useTonWallet } from "../lib/ton.js";
import { Sheet } from "../components/Sheet.jsx";
import { Flag } from "../components/Flags.jsx";
import { QrCode } from "../components/QrCode.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./account.css";
import { introApplies, planAmountKopecks } from "../lib/plans.js";

// Установки среди вкладок больше нет: она открывается кнопкой с карточки
// подписки и живёт экраном поверх. Держать её вкладкой значило звать туда
// каждый день, хотя заходят один раз — при подключении устройства.
const TABS = ["account", "plan", "friends"];

const SECTION_BY_TAB = {
  account: "",
  plan: "subscription",
  setup: "guide",
  friends: "friends",
  profile: "profile",
};
const TAB_BY_SECTION = { subscription: "plan", guide: "setup", friends: "friends", profile: "profile" };

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
  // Установка и список ключей — экраны поверх кабинета, а не вкладки.
  const [setupOpen, setSetupOpen] = useState(false);
  const [keysOpen, setKeysOpen] = useState(false);

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
  const [pwOpen, setPwOpen] = useState(false);
  const [walletOpen, setWalletOpen] = useState(false);
  const wallet = useTonWallet();

  // Аватар из Telegram — только внутри мини-аппа; подпись проверяет сервер,
  // фото — чистая витрина.
  // Фото профиля — только с серверов Telegram: адрес приходит из хеша,
  // который может подсунуть и чужая ссылка.
  const rawPhoto = isTma() ? tmaUser()?.photo_url : null;
  const tgPhoto = rawPhoto && /^https:\/\/t\.me\//.test(rawPhoto) ? rawPhoto : null;

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

  // Профиль — не вкладка, а пуш-экран поверх «Аккаунта»: шапку и таббар
  // он накрывает целиком, назад — системная кнопка Telegram (или стрелка).
  const isProfile = tab === "profile";
  const shownTab = isProfile ? "account" : tab;

  const [title, subtitle] = raw(`account.heads.${shownTab}`);

  return (
    <div className="ac">
      <header className="ac-header">
        <div className="wrap ac-header-in">
          <Link to="/" className="ac-logo">
            <Picture src="/assets/logo-v3.png" alt="PROSTO" />
          </Link>
          <CabinetNav tabs={TABS} tab={shownTab} hrefOf={sectionPath} />
          <button
            type="button"
            className="ac-id"
            onClick={() => {
              tmaHaptic("select");
              navigate(sectionPath("profile"));
            }}
          >
            <span className="ac-avatar">
              {tgPhoto ? (
                <img src={tgPhoto} alt="" referrerPolicy="no-referrer" />
              ) : isTma() ? (
                <img src="/assets/guide/app-icon.webp" alt="" />
              ) : (
                (data?.login || "P").slice(0, 1).toUpperCase()
              )}
            </span>
            <span className="ac-id-name">{data?.login || t("account.fallbackName")}</span>
            <svg
              className="ac-id-chev"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9.6 6.4 15.2 12l-5.6 5.6" />
            </svg>
          </button>
          {wallet ? (
            <button
              type="button"
              className="ac-wallet ac-wallet-on"
              onClick={() => setWalletOpen(true)}
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M3.6 7.2A2.2 2.2 0 0 1 5.8 5h11a2.2 2.2 0 0 1 2.2 2.2v9.6A2.2 2.2 0 0 1 16.8 19H5.8a2.2 2.2 0 0 1-2.2-2.2V7.2Z" />
                <path d="M19 10h1.4v4H19a2 2 0 1 1 0-4Z" />
              </svg>
              {shortAddress(tonAddress(wallet))}
            </button>
          ) : (
            // На установке кошелёк прячем: там человек занят одним делом —
            // подключиться, и вторая крупная кнопка сбивает с него.
            shownTab !== "setup" && (
              <button
                type="button"
                className="ac-wallet"
                onClick={() => {
                  tmaHaptic("select");
                  ensureConnected();
                }}
              >
                {t("profile.connectWallet")}
              </button>
            )
          )}
        </div>
      </header>

      <main className="wrap ac-main">
        {/* Состояние узлов — первое, что видно под шапкой: человек, у
            которого не подключается, должен увидеть причину до того, как
            пойдёт искать её в поддержке. */}
        <ServerStatus />

        {/* key по вкладке: контент каждый раз входит мягким подъёмом,
            а не подменяется скачком. */}
        <div className="ac-view" key={shownTab}>
        {shownTab !== "setup" && (
          <div className="ac-title">
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
        )}

        {error && <div className="ac-error">{error}</div>}

        {!data && !error && <TmaSkeleton variant={shownTab} />}

        {data && shownTab === "account" && (
          <AccountTab
            data={data}
            onManage={() => navigate(sectionPath("plan"))}
            onSetup={() => setSetupOpen(true)}
            onKeys={() => setKeysOpen(true)}
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
        {data && tab === "friends" && <TmaFriends />}
        </div>
      </main>

      <ScreenShell
        open={isProfile}
        title={raw("account.heads.profile")[0]}
        back={!isTma()}
        headless={isTma()}
        onClose={() => navigate(sectionPath("account"))}
      >
        {data ? (
          <ProfileTab
            data={data}
            tgPhoto={tgPhoto}
            onPassword={() => setPwOpen(true)}
            onSignOut={logout}
            onOpenWallet={() => setWalletOpen(true)}
            onAdblock={async (on) => {
              try {
                setData(await api.setAdblock(on));
              } catch {
                // не сохранилось — на экране останется прежнее значение
              }
            }}
          />
        ) : (
          <TmaSkeleton variant="profile" />
        )}
      </ScreenShell>

      <AppsScreen
        open={setupOpen}
        onClose={() => setSetupOpen(false)}
        onKeys={() => setKeysOpen(true)}
      />
      <TmaExternalKeys open={keysOpen} onClose={() => setKeysOpen(false)} />

      <WalletSheet open={walletOpen} onClose={() => setWalletOpen(false)} />

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
              tmaAlert(t("password.tmaDone"));
              return;
            } catch {
              // не вышло — честная форма входа
            }
          }
          navigate("/login", { replace: true });
        }}
      />

      <CabinetBottomNav tabs={TABS} tab={shownTab} hrefOf={sectionPath} />
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
  mail: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3.5" y="5.5" width="17" height="13" rx="2.5" />
      <path d="M4.5 7.5l7.5 5.5 7.5-5.5" />
    </svg>
  ),
  windows: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 5.5l7-1v7H4v-6zM13 4.2l7-1v8.3h-7V4.2zM4 13.5h7v7l-7-1v-6zM13 13.5h7v8.3l-7-1v-7.3z" />
    </svg>
  ),
  android: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 15a7 7 0 0 1 14 0v3H5v-3z" />
      <path d="M7 8l-1.6-2.6M17 8l1.6-2.6" />
      <circle cx="9.4" cy="13" r="0.6" fill="currentColor" />
      <circle cx="14.6" cy="13" r="0.6" fill="currentColor" />
    </svg>
  ),
  laptop: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="5" width="14" height="10" rx="1.6" />
      <path d="M3 19h18" />
    </svg>
  ),
  tv: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="11" rx="2" />
      <path d="M9 20h6" />
    </svg>
  ),
  phone: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="7" y="3" width="10" height="18" rx="2.5" />
      <path d="M11 17.5h2" />
    </svg>
  ),
  // Яблоко, а не безликий прямоугольник: рядом с роботом Android и окнами
  // Windows человек узнаёт свою платформу мгновенно, не читая подпись.
  // Заливка, а не обводка — логотип так и рисуется.
  apple: (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M17.05 12.54c-.02-2.51 2.05-3.71 2.14-3.77-1.17-1.71-2.99-1.95-3.63-1.97-1.55-.16-3.02.91-3.8.91-.78 0-1.99-.89-3.27-.87-1.68.03-3.23.98-4.09 2.48-1.74 3.03-.45 7.52 1.25 9.98.83 1.2 1.82 2.55 3.12 2.5 1.25-.05 1.72-.81 3.24-.81 1.51 0 1.94.81 3.27.78 1.35-.02 2.2-1.22 3.03-2.43.95-1.39 1.34-2.74 1.36-2.81-.03-.01-2.61-1-2.62-3.99z" />
      <path d="M14.9 4.6c.69-.83 1.15-1.99 1.02-3.14-.99.04-2.19.66-2.9 1.49-.64.73-1.19 1.91-1.04 3.03 1.1.09 2.23-.56 2.92-1.38z" />
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

const TMA_PLATFORMS = {
  windows: { icon: "windows", title: "Windows" },
  android: { icon: "android", title: "Android" },
  macos: { icon: "laptop", title: "macOS" },
  linux: { icon: "laptop", title: "Linux" },
  ios: { icon: "phone", title: "iPhone" },
};

function tmaConfirm(question, onYes) {
  const wa = window.Telegram?.WebApp;
  try {
    wa.showConfirm(question, (ok) => {
      if (ok) onYes();
    });
  } catch {
    if (window.confirm(question)) onYes();
  }
}

// Лист одного ключа iPhone: QR крупно, копия, открыть в AmneziaVPN,
// отключение и удаление — с системным подтверждением.
function TmaIosKeySheet({ open, group, onClose, onApply, onGuide }) {
  const { t } = useI18n();
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setIndex(0);
      setBusy(false);
      setCopied(false);
      setError("");
    }
  }, [open, group && group.slot]);

  if (!group) return null;
  const link = group.links[Math.min(index, group.links.length - 1)];

  const run = async (call, haptic = "medium") => {
    setBusy(true);
    setError("");
    try {
      const fresh = await call();
      tmaHaptic(haptic);
      onApply(fresh);
      onClose();
    } catch (err) {
      setError(err?.message || t("account.tmaFail"));
      setBusy(false);
    }
  };

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(link.vpn_url);
      tmaHaptic("light");
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  return (
    <SheetShell open={open} onClose={onClose}>
      <h2>
        {t("account.tmaKeyN", { n: group.slot })}
        {link.country ? ` · ${link.country}` : ""}
      </h2>
      <p className="pd-sub">{t("account.tmaKeySub")}</p>
      <button type="button" className="rf-how st-guide-link" onClick={() => onGuide(link)}>
        {t("account.tmaGuideBtn")} ›
      </button>

      {group.links.length > 1 && (
        <div className="st-servers">
          {group.links.map((one, i) => (
            <button
              key={one.server_id}
              type="button"
              className={`st-server${i === index ? " sel" : ""}`}
              onClick={() => setIndex(i)}
            >
              {one.country || one.server}
            </button>
          ))}
        </div>
      )}

      <div className="st-qr">
        <QrCode value={link.qr_payload || link.vpn_url} />
      </div>

      <button type="button" className="ap-cta" onClick={copyKey}>
        {copied ? t("account.tmaCopied") : t("account.tmaKeyCopy")}
      </button>
      <button
        type="button"
        className="ap-cta st-open"
        onClick={() => tmaOpenApp(link.vpn_url)}
      >
        {t("account.tmaKeyOpen")}
      </button>

      {error && <div className="pd-error">{error}</div>}

      <div className="st-key-acts">
        <button
          type="button"
          className="tps-alt"
          disabled={busy}
          onClick={() =>
            tmaConfirm(t("account.tmaKeyOffAsk"), () =>
              run(() => api.disconnectIosKey(group.slot)),
            )
          }
        >
          {t("account.tmaKeyOff")}
        </button>
        <button
          type="button"
          className="tps-alt st-danger"
          disabled={busy}
          onClick={() =>
            tmaConfirm(t("account.tmaKeyDelAsk"), () =>
              run(() => api.deleteIosKey(group.slot)),
            )
          }
        >
          {t("account.tmaKeyDel")}
        </button>
      </div>
    </SheetShell>
  );
}

// Лист выбора сервера для нового ключа iPhone.
function TmaAddKeySheet({ open, servers, exists, onClose, onApply }) {
  const { t } = useI18n();
  const [picked, setPicked] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setPicked(servers[0]?.id ?? null);
      setBusy(false);
      setError("");
    }
  }, [open, servers]);

  const create = async () => {
    if (busy || picked == null) return;
    setBusy(true);
    setError("");
    try {
      const fresh = exists ? await api.addIosKey(picked) : await api.enableIos(picked);
      tmaHaptic("medium");
      onApply(fresh);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "no_subscription"
          ? t("account.iosNoSubscription")
          : err?.message || t("account.tmaFail"),
      );
      setBusy(false);
    }
  };

  return (
    <SheetShell open={open} onClose={onClose}>
      <h2>{t("account.tmaKeyAddT")}</h2>
      <p className="pd-sub">{t("account.tmaKeyAddS")}</p>
      <div className="tps-methods">
        {servers.map((server) => (
          <button
            key={server.id}
            type="button"
            className={`tps-method${picked === server.id ? " sel" : ""}`}
            onClick={() => setPicked(server.id)}
          >
            <span className="st-flag">
              <Flag code={server.country_code} />
            </span>
            <span className="ap-row-body">
              <span className="ap-row-t">{server.country || server.name}</span>
              {server.city && <span className="ap-row-s">{server.city}</span>}
            </span>
            {picked === server.id && <span className="tps-check">✓</span>}
          </button>
        ))}
      </div>
      {error && <div className="pd-error">{error}</div>}
      <button type="button" className="ap-cta" disabled={busy} onClick={create}>
        {busy ? "…" : t("account.tmaKeyAddCta")}
      </button>
    </SheetShell>
  );
}

const TMA_APPSTORE = "https://apps.apple.com/app/amneziavpn/id1600529900";

// Эмодзи пака на каждый шаг гайда.
const TMA_GUIDE_EMOJI = {
  windows: ["backpack", "thumbup", "goldkey", "fire", "hundred"],
  android: ["backpack", "thumbup", "goldkey", "fire", "hundred"],
  macos: ["backpack", "coffee", "goldkey", "fire", "hundred"],
  ios: ["star", "goldkey", "unlockem", "hundred"],
  store: ["globe", "goldkey", "star", "backpack", "hundred"],
  bypass: ["backpack", "globe", "thumbup", "nerd", "hundred"],
};

const TMA_GUIDE_HERO = {
  windows: "globe",
  android: "robot",
  macos: "coffee",
  ios: "wink",
  store: "shush",
  bypass: "unlockem",
};

// Скрины с лендинга к шагам гайда: индекс шага -> файл в /assets/guide/.
const TMA_GUIDE_SHOTS = {
  bypass: { 1: "guide-split-1", 2: "guide-split-2", 3: "guide-split-3", 4: "guide-split-4" },
};

// Инструкция-«путь»: линия квеста через живые эмодзи-узлы, отмечаемые
// шаги с прогрессом и празднование в конце. Кнопки — в нужных шагах.
function TmaGuideScreen({ open, platform, link, login, downloads, file, onClose }) {
  const { t, raw } = useI18n();
  const [copied, setCopied] = useState("");
  const [done, setDone] = useState([]);
  const [storeOpen, setStoreOpen] = useState(false);

  const storageKey = `prosto_guide_${platform}`;

  useEffect(() => {
    if (!open) return;
    setCopied("");
    setStoreOpen(false);
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      setDone(Array.isArray(saved) ? saved : []);
    } catch {
      setDone([]);
    }
  }, [open, platform]);

  if (!platform) return null;
  const steps = raw(`account.tmaGuide.${platform}`) || [];
  const emojis = TMA_GUIDE_EMOJI[platform] || [];
  const release = (downloads || []).find((row) => row.platform === platform);
  const title =
    platform === "store"
      ? t("account.tmaStoreTitle")
      : platform === "bypass"
        ? t("account.tmaBypassTitle")
        : TMA_PLATFORMS[platform]?.title || platform;
  const total = steps.length;
  const complete = total > 0 && done.length >= total;

  const toggle = (index) => {
    setDone((prev) => {
      const next = prev.includes(index)
        ? prev.filter((x) => x !== index)
        : [...prev, index];
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {}
      tmaHaptic(next.length === total && next.length > prev.length ? "medium" : "light");
      return next;
    });
  };

  const copy = async (kind, value) => {
    try {
      await navigator.clipboard.writeText(value);
      tmaHaptic("light");
      setCopied(kind);
      setTimeout(() => setCopied(""), 1400);
    } catch {}
  };

  return (
    <ScreenShell open={open} title={title} onClose={onClose}>
      <div className="gd2">
        <div className="gd2-hero">
          <span className="ap-ic ap-ic-emoji">
            <TgsEmoji name={TMA_GUIDE_HERO[platform] || "globe"} size={64} />
          </span>
          <span className="gd2-hero-b">
            <b>{t("account.tmaGuideMinutes")}</b>
            <span className="gd2-chips">
              <span className="gd2-chip">{t("account.tmaGuideSteps", { n: total })}</span>
              <span className={`gd2-chip${done.length ? " on" : ""}`}>
                {t("account.tmaGuideProgress", { done: done.length, total })}
              </span>
            </span>
          </span>
        </div>

        <div className="gd2-path">
          {steps.map(([head, text], index) => {
            const isDone = done.includes(index);
            return (
              <div
                key={index}
                className={`gd2-step${isDone ? " is-done" : ""}`}
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <span className="gd2-node">
                  <TgsEmoji name={emojis[index] || "sparkle"} size={32} />
                </span>
                <div className="gd2-card">
                  <div className="gd2-head">
                    <span className="gd2-t">
                      <i>{index + 1}</i>
                      {head}
                    </span>
                    <button
                      type="button"
                      className="gd2-check"
                      aria-label={head}
                      aria-pressed={isDone}
                      onClick={() => toggle(index)}
                    >
                      ✓
                    </button>
                  </div>
                  <span className="gd2-s">{text}</span>

                  {TMA_GUIDE_SHOTS[platform]?.[index] && (
                    <Picture
                      className="gd2-shot"
                      src={`/assets/guide/${TMA_GUIDE_SHOTS[platform][index]}.jpg`}
                      alt={head}
                    />
                  )}

                  {platform === "bypass" && index === 0 && file?.available && (
                    <>
                      <button
                        type="button"
                        className="ap-cta st-g-cta"
                        onClick={() => {
                          tmaHaptic("light");
                          tmaOpenLink(file.url);
                        }}
                      >
                        {t("account.tmaBypassDl")}
                      </button>
                      <button
                        type="button"
                        className="tps-alt st-g-alt"
                        onClick={() => copy("bypass", file.url)}
                      >
                        {copied === "bypass"
                          ? t("account.tmaCopied")
                          : t("account.tmaGuideCopyLink")}
                      </button>
                    </>
                  )}
                  {index === 0 && platform !== "ios" && release && (
                    <>
                      <a className="ap-cta st-g-cta" href={release.url} download>
                        {t("account.tmaGuideDl", { v: release.version })}
                      </a>
                      <button
                        type="button"
                        className="tps-alt st-g-alt"
                        onClick={() => copy("dl", release.url)}
                      >
                        {copied === "dl" ? t("account.tmaCopied") : t("account.tmaGuideCopyLink")}
                      </button>
                    </>
                  )}
                  {index === 0 && platform === "ios" && (
                    <>
                      <a className="ap-cta st-g-cta" href={TMA_APPSTORE}>
                        {t("account.tmaGuideStore")}
                      </a>
                      <button
                        type="button"
                        className="tps-alt st-g-alt"
                        onClick={() => copy("store", TMA_APPSTORE)}
                      >
                        {copied === "store"
                          ? t("account.tmaCopied")
                          : t("account.tmaGuideCopyLink")}
                      </button>
                      <span className="st-note">
                        {t("account.tmaGuideStoreMiss")}{" "}
                        <button
                          type="button"
                          className="st-note-link st-note-btn"
                          onClick={() => setStoreOpen(true)}
                        >
                          {t("account.tmaGuideStoreHow")}
                        </button>
                      </span>
                    </>
                  )}
                  {platform === "store" && index === 3 && (
                    <>
                      <a className="ap-cta st-g-cta" href={TMA_APPSTORE}>
                        {t("account.tmaGuideStore")}
                      </a>
                      <button
                        type="button"
                        className="tps-alt st-g-alt"
                        onClick={() => copy("store2", TMA_APPSTORE)}
                      >
                        {copied === "store2"
                          ? t("account.tmaCopied")
                          : t("account.tmaGuideCopyLink")}
                      </button>
                    </>
                  )}
                  {platform === "ios" && index === 1 && link && (
                    <>
                      <button
                        type="button"
                        className="ap-cta st-g-cta"
                        onClick={() => tmaOpenApp(link.vpn_url)}
                      >
                        {t("account.tmaKeyOpen")}
                      </button>
                      <button
                        type="button"
                        className="tps-alt st-g-alt"
                        onClick={() => copy("key", link.vpn_url)}
                      >
                        {copied === "key" ? t("account.tmaCopied") : t("account.tmaKeyCopy")}
                      </button>
                    </>
                  )}
                  {platform !== "ios" && platform !== "bypass" && index === 2 && (
                    <button
                      type="button"
                      className="st-login st-g-login"
                      onClick={() => copy("login", login)}
                    >
                      <span className="ap-row-s">{t("account.tmaSetupLogin")}</span>
                      <b>{copied === "login" ? t("account.tmaCopied") : login}</b>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {platform === "ios" && (
          <TmaGuideScreen
            open={storeOpen}
            platform="store"
            login={login}
            downloads={downloads}
            onClose={() => setStoreOpen(false)}
          />
        )}

        {complete && (
          <div className="gd2-done">
            <span className="gd2-confetti" aria-hidden="true">
              {Array.from({ length: 12 }, (_, i) => (
                <i key={i} style={{ "--i": i }} />
              ))}
            </span>
            <TgsEmoji name="hundred" size={64} />
            <b>{t("account.tmaGuideDoneT")}</b>
            <span>{t("account.tmaGuideDoneS")}</span>
            <button type="button" className="ap-cta gd2-done-cta" onClick={onClose}>
              {t("account.tmaGuideDoneCta")}
            </button>
          </div>
        )}
      </div>
    </ScreenShell>
  );
}

// Файл обхода — лист: скачивание через внешний браузер (в вебвью файл
// открылся бы просмотром) и копия ссылки.
function TmaBypassSheet({ open, file, onGuide, onClose }) {
  const { t, f } = useI18n();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (open) setCopied(false);
  }, [open]);

  if (!file?.available) return null;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(file.url);
      tmaHaptic("light");
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  return (
    <SheetShell open={open} onClose={onClose}>
      <h2>{t("account.tmaBypassTitle")}</h2>
      <p className="pd-sub">{t("account.bypassText")}</p>
      <button type="button" className="rf-how st-guide-link" onClick={onGuide}>
        {t("account.tmaGuideBtn")} ›
      </button>
      <span className="st-note">
        {file.updated_at
          ? t("account.bypassUpdated", { date: f.longDate(file.updated_at) }) +
            (file.size_bytes ? ` · ${f.bytes(file.size_bytes)}` : "")
          : ""}
      </span>
      <button
        type="button"
        className="ap-cta"
        onClick={() => {
          tmaHaptic("light");
          tmaOpenLink(file.url);
        }}
      >
        {t("account.tmaBypassDl")}
      </button>
      <button type="button" className="tps-alt" onClick={copyLink}>
        {copied ? t("account.tmaCopied") : t("account.tmaGuideCopyLink")}
      </button>
    </SheetShell>
  );
}

// Главная мини-аппа: карта статуса с круглой CTA, пауза, действия и
// аккаунт — группами строк. Стиль нативных мини-аппов, наш цвет.
function TmaHome({ data, used, onManage, onSetup, onKeys, onFriends, onPassword, onChanged, onApply }) {
  const { t, f } = useI18n();
  const frozen = Boolean(data.freeze?.frozen);
  const file = data.tunnel_file;
  const [copied, setCopied] = useState(null);
  const [emailOpen, setEmailOpen] = useState(false);
  const [bypassOpen, setBypassOpen] = useState(false);
  const [bypassGuide, setBypassGuide] = useState(false);
  const [devicesOpen, setDevicesOpen] = useState(false);
  // Подсказка про регион App Store: сама показывается один раз за заход
  // и уходит, если её не трогать; «Больше не показывать» гасит навсегда.
  const [storeOpen, setStoreOpen] = useState(false);
  useEffect(() => {
    if (!appStoreAutoAllowed()) return undefined;
    const id = setTimeout(() => {
      markAppStoreShown();
      setStoreOpen(true);
    }, 900);
    return () => clearTimeout(id);
  }, []);

  // Иерархия карты: статус — точкой и словом, дни — крупной цифрой,
  // тариф — чипом, точная дата — мелко. Никаких предложений из данных.
  const status = frozen
    ? t("account.tmaStatusFrozen")
    : data.active
      ? t("account.tmaStatusOn")
      : t("account.tmaStatusOff");

  // Копирование по тапу: «Скопировано» загорается на той строке, которую
  // нажали, и само гаснет.
  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied((cur) => (cur === key ? null : cur)), 1400);
    } catch {}
  };

  return (
    <div className="ap ap-home">
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
            {/* Когда всё в порядке, строка «работает» не несёт ничего:
                крупная цифра дней ниже говорит то же самое и точнее. Пауза
                и закончившаяся подписка — другое дело, их видно словом. */}
            {(frozen || !data.active) && (
              <span className="ap-status">
                <span className={`ap-dot${frozen ? " is-frozen" : " is-off"}`} />
                {status}
              </span>
            )}
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
        {/* Два действия вместо одного: продлить и подключить устройство —
            разные задачи, и раньше вторая пряталась во вкладке, куда никто
            не заходил. Продление слева и залито: за ним приходят чаще. */}
        <div className="ap-duo">
          <button className="ap-cta" onClick={onManage}>
            {t("account.renew")}
          </button>
          <button className="ap-cta ap-cta-alt" onClick={onSetup}>
            {t("account.setupBtn")}
          </button>
        </div>
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
          title={t("account.tmaKeysTitle")}
          sub={t("account.tmaKeysSub")}
          onClick={onKeys}
        />
        <ApRow
          icon="phone"
          title={t("account.tmaDevicesRow")}
          sub={t("account.tmaDevicesRowSub", { used, total: data.device_limit })}
          onClick={() => setDevicesOpen(true)}
        />
        <ApRow
          icon="file"
          title={t("account.tmaBypassTitle")}
          sub={t("account.tmaBypassSub")}
          onClick={() => setBypassOpen(true)}
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
        <ApRow
          icon="person"
          title={t("account.fieldLogin")}
          value={copied === "login" ? t("account.tmaCopied") : data.login}
          onClick={() => copy("login", data.login)}
        />
        <ApRow
          icon="mail"
          title={t("account.fieldEmail")}
          value={data.email || t("account.emailEmpty")}
          onClick={() => setEmailOpen(true)}
        />
        <ApRow icon="lock" title={t("account.changePassword")} onClick={onPassword} />
        <ApRow
          icon="file"
          title={t("account.statPublicId")}
          value={copied === "id" ? t("account.tmaCopied") : data.public_id}
          onClick={() => copy("id", data.public_id)}
        />
      </div>

      <EmailDialog
        open={emailOpen}
        email={data.email}
        onClose={() => setEmailOpen(false)}
        onChanged={onChanged}
      />
      <TmaDevicesSheet
        open={devicesOpen}
        data={data}
        onClose={() => setDevicesOpen(false)}
        onChanged={onChanged}
        onApply={onApply}
      />
      <AppStoreSheet open={storeOpen} auto onClose={() => setStoreOpen(false)} />
      <TmaBypassSheet
        open={bypassOpen}
        file={file}
        onGuide={() => {
          setBypassOpen(false);
          setBypassGuide(true);
        }}
        onClose={() => setBypassOpen(false)}
      />
      <TmaGuideScreen
        open={bypassGuide}
        platform="bypass"
        file={file}
        onClose={() => setBypassGuide(false)}
      />
    </div>
  );
}

// «Как это работает» — отдельная страница с баннером-персонажами из пака.
function TmaRefHow({ open, onClose, data, onCopy, copied }) {
  const { t, f } = useI18n();
  if (!data) return null;
  return (
    <ScreenShell open={open} title={t("account.tmaHowTitle")} onClose={onClose}>
      <div className="ap">
        <div className="hw-banner">
          <span className="hw-fig">
            <span className="hw-badge">{t("account.tmaHowShare")}</span>
            <TgsEmoji name="wink" size={56} />
            <span className="hw-name">{t("account.tmaHowYou")}</span>
          </span>
          <span className="hw-line" aria-hidden="true" />
          <span className="hw-fig">
            <span className="hw-badge">+{f.days(data.join_days)}</span>
            <TgsEmoji name="shush" size={56} />
            <span className="hw-name">{t("account.tmaHowFriend")}</span>
          </span>
          <span className="hw-line" aria-hidden="true" />
          <span className="hw-fig">
            <span className="hw-badge">+{f.days(data.join_days)}</span>
            <TgsEmoji name="laugh" size={56} />
            <span className="hw-name">{t("account.tmaHowFriend2")}</span>
          </span>
        </div>

        <div className="ap-card hw-card">
          <h2>{t("account.tmaHowJoinT", { days: f.days(data.join_days) })}</h2>
          <p>{t("account.tmaHowJoinS")}</p>
        </div>
        <div className="ap-card hw-card">
          <h2>{t("account.tmaHowPayT", { days: f.days(data.purchase_days) })}</h2>
          <p>{t("account.tmaHowPayS")}</p>
        </div>
        <div className="ap-card hw-card">
          <h2>{t("account.tmaHowStackT")}</h2>
          <p>{t("account.tmaHowStackS")}</p>
        </div>

        <button type="button" className="scr-cta" onClick={onCopy}>
          {copied ? t("account.tmaCopied") : t("account.tmaHowCopy")}
        </button>
      </div>
    </ScreenShell>
  );
}

// «Друзья» мини-аппа: ссылка запускает само приложение (startapp=код),
// делиться — нативным телеграм-шэром.
// Скелет страницы: каркас блоков с шиммером на месте контента, пока идёт
// загрузка — вместо мигания пустотой при переключении вкладок.
function TmaSkeleton({ variant }) {
  if (variant === "plan")
    return (
      <div className="ap" aria-hidden="true">
        <span className="sk" style={{ height: 96 }} />
        <div className="sk-grid">
          <span className="sk" style={{ height: 136 }} />
          <span className="sk" style={{ height: 136 }} />
          <span className="sk" style={{ height: 136 }} />
          <span className="sk" style={{ height: 136 }} />
        </div>
        <span className="sk" style={{ height: 64 }} />
      </div>
    );
  if (variant === "setup")
    return (
      <div className="ap" aria-hidden="true">
        <span className="sk" style={{ height: 64 }} />
        <span className="sk" style={{ height: 190 }} />
        <span className="sk" style={{ height: 64 }} />
        <span className="sk" style={{ height: 64 }} />
      </div>
    );
  if (variant === "friends")
    return (
      <div className="ap" aria-hidden="true">
        <span className="sk" style={{ height: 178 }} />
        <span className="sk" style={{ height: 64 }} />
        <span className="sk" style={{ height: 132 }} />
      </div>
    );
  return (
    <div className="ap" aria-hidden="true">
      <span className="sk" style={{ height: 168 }} />
      <span className="sk" style={{ height: 250 }} />
      <span className="sk" style={{ height: 64 }} />
    </div>
  );
}

function TmaFriends() {
  const { t, f } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [howOpen, setHowOpen] = useState(false);
  const [histOpen, setHistOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .referrals()
      .then((body) => alive && setData(body))
      .catch((err) =>
        alive && setError(err instanceof ApiError ? err.message : t("account.refFailed")),
      );
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <p className="scr-empty">{error}</p>;
  if (!data)
    return (
      <div className="ap" aria-hidden="true">
        <span className="sk" style={{ height: 178 }} />
        <span className="sk" style={{ height: 64 }} />
        <span className="sk" style={{ height: 132 }} />
      </div>
    );

  const code = (() => {
    try {
      return new URL(data.site_url).searchParams.get("ref") || "";
    } catch {
      return "";
    }
  })();
  // В Telegram зовём в мини-апп (реферал ловится через start_param), на
  // сайте раздаём обычную ссылку с ?ref= — как делал старый веб-кабинет.
  const appLink =
    isTma() && code && data.bot_url ? `${data.bot_url}?startapp=${code}` : data.site_url;

  const share = () => {
    const url =
      "https://t.me/share/url?url=" +
      encodeURIComponent(appLink) +
      "&text=" +
      encodeURIComponent(t("account.refShareText"));
    try {
      const wa = window.Telegram?.WebApp;
      // Метод существует и в браузере (заменил бы вкладку на t.me) —
      // пользуемся им только внутри Telegram.
      if (isTma() && wa?.openTelegramLink) {
        wa.openTelegramLink(url);
        return;
      }
    } catch {}
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(appLink);
      tmaHaptic("light");
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  return (
    <div className="ap ap-friends">
      <div className="ap-card">
        <div className="ap-head">
          <span className="ap-ic ap-ic-emoji">
            <TgsEmoji name="popcorn" size={62} />
          </span>
          <span className="ap-head-body">
            <span className="ap-title">{t("account.tmaRefTitle2")}</span>
            <span className="ap-sub">{t("account.tmaRefSub2")}</span>
            <button type="button" className="rf-how" onClick={() => setHowOpen(true)}>
              {t("account.tmaHowLink")} ›
            </button>
          </span>
        </div>
        <div className="rf-bonus" aria-hidden="true">
          <span className="rf-chip">
            {t("account.tmaRefChipJoin", { days: f.days(data.join_days) })}
          </span>
          <span className="rf-chip">
            {t("account.tmaRefChipPay", { days: f.days(data.purchase_days) })}
          </span>
        </div>
        <div className="rf-link-box">
          <code>{appLink}</code>
        </div>
        <button type="button" className="ap-cta" onClick={share}>
          {t("account.tmaRefShare")}
        </button>
        <button type="button" className="tps-alt" onClick={copy}>
          {copied ? t("account.tmaCopied") : t("account.refCopy")}
        </button>
      </div>

      <div className="rf-tiles">
        <div className="rf-tile">
          <b>{data.invited}</b>
          <span>{t("account.refStatInvited")}</span>
        </div>
        <div className="rf-tile">
          <b>{f.days(data.days_total)}</b>
          <span>{t("account.tmaRefDays")}</span>
        </div>
      </div>

      <div className="ap-rows">
        <ApRow
          icon="gift"
          title={t("account.tmaRefHistT")}
          sub={t("account.tmaRefHistS")}
          onClick={() => setHistOpen(true)}
        />
      </div>

      <TmaRefHow
        open={howOpen}
        onClose={() => setHowOpen(false)}
        data={data}
        copied={copied}
        onCopy={copy}
      />
      <TmaRefHistoryScreen
        open={histOpen}
        onClose={() => setHistOpen(false)}
        friends={data.friends}
      />
    </div>
  );
}

// История начислений за друзей — отдельная страница.
function TmaRefHistoryScreen({ open, onClose, friends }) {
  const { t, f } = useI18n();
  return (
    <ScreenShell open={open} title={t("account.tmaRefHistT")} onClose={onClose}>
      {friends.length === 0 ? (
        <p className="scr-empty">{t("account.refEmpty")}</p>
      ) : (
        <div className="scr-rows">
          {friends.map((friend, index) => (
            <div className="scr-row rf-friend" key={friend.joined_at + ":" + index}>
              <span className="ap-row-body">
                <span className="ap-row-t">
                  {t("account.refFriend", { n: friends.length - index })}
                </span>
                <span className="ap-row-s">
                  {t("account.refCame", { date: f.shortDate(friend.joined_at) })}
                  {friend.paid ? " · " + t("account.refPaid") : ""}
                </span>
              </span>
              <b className={friend.pending ? "rf-wait" : "scr-in"}>
                {friend.pending ? t("account.refWaiting") : "+" + f.days(friend.days)}
              </b>
            </div>
          ))}
        </div>
      )}
    </ScreenShell>
  );
}

function AccountTab({ data, onManage, onSetup, onKeys, onFriends, onPassword, onChanged, onApply }) {
  const { t, f } = useI18n();
  // Цифра приходит с сервера тем же правилом, что и список: входы
  // приложения + выданные ключи iPhone + ссылки для Happ. Старый ответ без
  // поля — считаем по списку.
  const used = data.devices_used ?? data.devices.length;
  const free = Math.max(0, data.device_limit - used);

  // Карточный формат — один для сайта и Telegram; старый веб-вид ниже
  // недостижим и ждёт выпиливания.
  {
    return (
      <TmaHome
        data={data}
        used={used}
        onManage={onManage}
        onSetup={onSetup}
        onKeys={onKeys}
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
  const isLink = device.kind === "sub_link";

  const unlink = async () => {
    setBusy(true);
    setError("");
    try {
      if (isKey) {
        onApply(await api.disconnectIosKey(device.slot));
      } else if (isLink) {
        // Ссылку отзываем: приложения, куда её вставили, перестанут
        // получать ключи, а место по тарифу освободится.
        await api.revokeSubscriptionKey(device.key_id);
        onChanged();
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
    happ: t("account.platformHapp"),
    web: t("account.platformWeb"),
  };

  const name = isKey
    ? t("account.iosDeviceName", { n: device.slot })
    : isLink
      ? device.name || t("account.subLinkName", { n: device.slot })
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
            : device.last_seen_at
              ? ` · ${f.ago(device.last_seen_at)}`
              : ` · ${t("account.neverConnected")}`}
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

const PAY_METHODS = [
  { id: "sbp", Icon: SbpIcon, title: "tmaMethSbp", sub: "tmaMethSbpSub" },
  { id: "ton", Icon: TonIcon, title: "tmaMethTon", sub: "tmaMethTonSub" },
  { id: "stars", Icon: TelegramIcon, title: "tmaMethStars", sub: "tmaMethStarsSub" },
  { id: "crypto", Icon: CryptoIcon, title: "tmaMethCrypto", sub: "tmaMethCryptoSub" },
];

// Лист оплаты мини-аппа: способы строками с галочкой, большая круглая CTA;
// после создания счёта — ожидание с поллингом (логика в PlanTab).
function TmaPaySheet({ open, plan, quantity, busyMethod, invoice, onPay, onNewInvoice, onClose }) {
  const { t, f } = useI18n();
  const [method, setMethod] = useState("sbp");

  useEffect(() => {
    if (open) setMethod("sbp");
  }, [open]);

  if (!plan) return null;
  // Столько спишут сейчас — то же правило, что и на бэкенде.
  const price = f.moneyFromKopecks(planAmountKopecks(plan, quantity), plan.currency);
  const introHint = introApplies(plan, quantity)
    ? t("pay.introThen", { price: f.moneyFromKopecks(plan.price_kopecks, plan.currency) })
    : null;
  const openInvoice = () => {
    // TON-счёт открывается не ссылкой, а повторным запросом подписи в кошельке.
    if (invoice.method === "ton") {
      tonPay(invoice.url).catch(() => {});
      return;
    }
    try {
      const wa = window.Telegram?.WebApp;
      if (wa?.openLink) wa.openLink(invoice.url);
      else window.open(invoice.url, "_blank", "noopener,noreferrer");
    } catch {}
  };

  let body;
  if (invoice && invoice.status === "paid") {
    body = (
      <>
        <div className="tps-state tps-ok">✓</div>
        <h2 className="tps-center">{t("account.tmaPayPaid")}</h2>
        <p className="pd-sub tps-center">{t("account.tmaPayPaidSub")}</p>
        <button type="button" className="ap-cta" onClick={onClose}>
          {t("account.tmaPayDone")}
        </button>
      </>
    );
  } else if (invoice && invoice.status === "failed") {
    body = (
      <>
        <div className="tps-state tps-bad">!</div>
        <h2 className="tps-center">{t("account.tmaPayFailed")}</h2>
        <button type="button" className="ap-cta" onClick={onNewInvoice}>
          {t("account.tmaPayRetry")}
        </button>
      </>
    );
  } else if (invoice) {
    body = (
      <>
        <div className="tps-state tps-wait" aria-hidden="true" />
        <h2 className="tps-center">{t("account.tmaPayWaiting")}</h2>
        <p className="pd-sub tps-center">{t("account.tmaPayWaitingSub")}</p>
        <button type="button" className="ap-cta" onClick={openInvoice}>
          {t("account.tmaPayOpen")}
        </button>
        <button type="button" className="tps-alt" onClick={onNewInvoice}>
          {t("account.tmaPayAnother")}
        </button>
      </>
    );
  } else {
    body = (
      <>
        <h2>{t("account.tmaPayTitle")}</h2>
        <p className="pd-sub">
          {plan.title} · {price}
          {introHint && <span className="pay-intro"> · {introHint}</span>}
        </p>
        <div className="tps-methods">
          {PAY_METHODS.map(({ id, Icon, title, sub }) => (
            <button
              key={id}
              type="button"
              className={`tps-method${method === id ? " sel" : ""}`}
              onClick={() => setMethod(id)}
            >
              <span className="tps-mic">
                <Icon />
              </span>
              <span className="ap-row-body">
                <span className="ap-row-t">{t(`account.${title}`)}</span>
                <span className="ap-row-s">{t(`account.${sub}`)}</span>
              </span>
              {method === id && <span className="tps-check">✓</span>}
            </button>
          ))}
        </div>
        {method === "stars" ? (
          <a className="ap-cta tps-cta" href={starsPayUrl(plan.code)} target="_blank" rel="noopener">
            {t("account.tmaStarsGo")}
          </a>
        ) : (
          <button
            type="button"
            className="ap-cta"
            disabled={Boolean(busyMethod)}
            onClick={() => onPay(method)}
          >
            {busyMethod ? "…" : t("account.tmaPayCta", { price })}
          </button>
        )}
        <p className="tps-hint">
          {method === "stars" ? t("account.tmaStarsHint") : "\u00a0"}
        </p>
      </>
    );
  }

  return (
    <SheetShell open={open} onClose={busyMethod ? () => {} : onClose}>
      {body}
    </SheetShell>
  );
}

// Передача дней другу — лист с получателем и степпером дней.
function TmaTransferSheet({ open, data, onClose, onChanged, onHistory }) {
  const { t, f } = useI18n();
  const [recipient, setRecipient] = useState("");
  const [days, setDays] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setRecipient("");
      setDays(1);
      setError("");
      setBusy(false);
    }
  }, [open]);

  const left = data.days_left || 0;
  const amount = Number(days) || 0;
  const ready = recipient.trim().length > 0 && amount >= 1 && amount <= left;

  const send = async (e) => {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.transferDays(recipient.trim(), amount);
      tmaHaptic("medium");
      onClose();
      onChanged();
      tmaAlert(t("account.trSent", { days: f.days(amount) }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.trFailed"));
      setBusy(false);
    }
  };

  return (
    <SheetShell open={open} onClose={onClose} onSubmit={send}>
      <h2>{t("account.trTitle")}</h2>
      <p className="pd-sub">{t("account.trHint", { left: f.days(left) })}</p>

      <label className="pd-field">
        <span>{t("account.tmaTrRecipient")}</span>
        <input
          value={recipient}
          onChange={(e) => setRecipient(e.target.value)}
          placeholder="prosto_user"
          autoComplete="off"
        />
      </label>

      <label className="pd-field">
        <span>{t("account.tmaTrDays")}</span>
        <div className="tps-stepper">
          <button
            type="button"
            className="tps-step"
            disabled={amount <= 1}
            onClick={() => setDays(Math.max(1, amount - 1))}
          >
            −
          </button>
          <input
            inputMode="numeric"
            value={days}
            onChange={(e) => {
              const digits = e.target.value.replace(/\D/g, "").slice(0, 3);
              setDays(digits ? Number(digits) : "");
            }}
            onBlur={() => setDays((n) => (Number(n) >= 1 ? Number(n) : 1))}
          />
          <button
            type="button"
            className="tps-step"
            disabled={amount >= left}
            onClick={() => setDays(Math.min(left, amount + 1))}
          >
            +
          </button>
        </div>
      </label>

      {amount > left && left > 0 && <div className="pd-error">{t("account.trTooMany")}</div>}
      {error && <div className="pd-error">{error}</div>}

      <div className="pd-actions">
        <button type="button" className="btn btn-outline" onClick={onHistory}>
          {t("account.tmaTrHistory")}
        </button>
        <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
          {busy ? t("password.busy") : t("account.tmaTrSend")}
        </button>
      </div>
    </SheetShell>
  );
}

// История передач — отдельный экран.
function TmaTransfersScreen({ open, onClose }) {
  const { t, f } = useI18n();
  const [rows, setRows] = useState(null);

  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    api
      .transfers()
      .then((list) => alive && setRows(Array.isArray(list) ? list : []))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [open]);

  return (
    <ScreenShell open={open} title={t("account.tmaTrHistTitle")} onClose={onClose}>
      {rows === null ? (
        <p className="scr-empty">{t("account.plansLoading")}</p>
      ) : rows.length === 0 ? (
        <p className="scr-empty">{t("account.tmaTrHistEmpty")}</p>
      ) : (
        <div className="scr-rows">
          {rows.map((row) => (
            <div className="scr-row" key={row.id}>
              <span className="ap-row-body">
                <span className="ap-row-t">
                  {t(row.direction === "sent" ? "account.trTo" : "account.trFrom", {
                    who: row.counterpart,
                  })}
                </span>
                <span className="ap-row-s">{f.shortDate(row.created_at)}</span>
              </span>
              <b className={row.direction === "sent" ? "scr-out" : "scr-in"}>
                {row.direction === "sent" ? "−" : "+"}
                {f.days(row.days)}
              </b>
            </div>
          ))}
        </div>
      )}
    </ScreenShell>
  );
}

// История платежей — отдельный экран. Тап по строке копирует номер заказа.
function TmaPaymentsScreen({ open, payments, onClose }) {
  const { t, f } = useI18n();
  const [copied, setCopied] = useState(null);

  const orderNo = (row) => ((row.comment || "").match(/[0-9a-f-]{8,}/i) || [null])[0];

  const copyRow = async (row, i) => {
    const no = orderNo(row);
    if (!no) return;
    try {
      await navigator.clipboard.writeText(no);
      tmaHaptic("light");
      setCopied(i);
      setTimeout(() => setCopied((cur) => (cur === i ? null : cur)), 1400);
    } catch {}
  };

  return (
    <ScreenShell open={open} title={t("account.paymentsTitle")} onClose={onClose}>
      {payments.length === 0 ? (
        <p className="scr-empty">{t("account.paymentsEmpty")}</p>
      ) : (
        <div className="scr-rows">
          {payments.map((row, i) => (
            <button type="button" className="scr-row" key={i} onClick={() => copyRow(row, i)}>
              <span className="ap-row-body">
                <span className="ap-row-t">{row.comment || t("account.payFallback")}</span>
                <span className="ap-row-s">
                  {copied === i
                    ? t("account.tmaOrderCopied")
                    : `${f.longDate(row.paid_at)}${orderNo(row) ? " · " + t("account.tmaTapToCopy") : ""}`}
                </span>
              </span>
              <b className="scr-in">{f.money(row.amount, row.currency)}</b>
            </button>
          ))}
        </div>
      )}
    </ScreenShell>
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

  // Мини-апп: выбранный тариф (карточка + прилипшая CTA) и под-экраны.
  const [selected, setSelected] = useState(preselected || null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [showTransfers, setShowTransfers] = useState(false);
  const [showPayments, setShowPayments] = useState(false);

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

  useEffect(() => {
    if (!plans || !plans.length) return;
    setSelected((cur) => {
      if (cur && plans.some((p) => p.code === cur)) return cur;
      const nonDaily = plans.filter((p) => !isDaily(p));
      const perDay = (p) => p.price_kopecks / p.duration_days;
      const best = nonDaily.reduce(
        (a, b) => (a === null || perDay(b) < perDay(a) ? b : a),
        null,
      );
      return (best || plans[0]).code;
    });
  }, [plans]);

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
    if (!invoice || invoice.status !== "pending" || invoice.dismissed || paying || !plans) return;
    const plan = plans.find((p) => p.code === invoice.planCode);
    if (plan) {
      setPaying(plan);

      if (invoice.quantity) setDailyDays(invoice.quantity);
    }
  }, [invoice && invoice.orderId, invoice && invoice.status, plans]);

  const payWith = async (method) => {
    if (!paying || busyMethod) return;
    const days = isDaily(paying) ? dailyDays : 1;
    const tma = isTma();
    // TON подписывается в кошельке через TON Connect — внешняя вкладка не нужна.
    const win = tma || method === "ton" ? null : window.open("about:blank", "_blank");
    setBusyMethod(method);
    setNotice("");
    try {
      const order = await api.renew(paying.code, days, method);
      if (order && order.redirect_url) {
        if (method === "ton") {
          setInvoice({
            planCode: paying.code,
            orderId: order.id,
            url: order.redirect_url,
            quantity: days,
            status: "pending",
            method: "ton",
          });
          setBusyMethod(null);
          try {
            await tonPay(order.redirect_url);
          } catch (err) {
            // Человек передумал в кошельке — счёт остаётся ждать, вдруг
            // оплатит по кнопке «Открыть» ещё раз.
            if (err?.message) setNotice("");
          }
          return;
        }
        if (tma) {
          // Внутри Telegram страницу оплаты открывает сам клиент — во
          // внешнем браузере; window.open в вебвью ненадёжен.
          try {
            window.Telegram?.WebApp?.openLink?.(order.redirect_url);
          } catch {}
        } else if (win) {
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

  // Витрина одна для всех — карточный формат.
  {
    const nonDaily = ordered.filter((plan) => !isDaily(plan));
    const daily = ordered.find(isDaily) || null;
    const perDay = (plan) => plan.price_kopecks / plan.duration_days;
    const base = nonDaily.length ? Math.max(...nonDaily.map(perDay)) : 0;
    const saveOf = (plan) => (base ? Math.round((1 - perDay(plan) / base) * 100) : 0);
    const best = nonDaily.reduce(
      (a, b) => (a === null || saveOf(b) > saveOf(a) ? b : a),
      null,
    );
    const selPlan = list.find((plan) => plan.code === selected) || null;
    const qty = selPlan && isDaily(selPlan) ? Number(dailyDays) || 1 : 1;
    const total = data.period_days || 0;
    const frac =
      total && data.days_left != null
        ? Math.max(0.02, Math.min(1, data.days_left / total))
        : null;

    const startPay = () => {
      setInvoice((inv) => (inv && inv.dismissed ? { ...inv, dismissed: false } : inv));
      if (!selPlan) return;
      if (invoice && invoice.planCode === selPlan.code && invoice.status !== "pending") {
        setInvoice(null);
      }
      setPaying(selPlan);
    };

    return (
      <div className="ap tp">
        {notice && (
          <div className="ac-notice" role="alert" ref={noticeRef}>
            {notice}
          </div>
        )}

        {frac !== null && (
          <div className="tp-progress">
            <div className="tp-progress-top">
              <b>{f.days(data.days_left)}</b>
              <span>
                {data.expires_at
                  ? t("account.tmaUntil", { date: f.shortDate(data.expires_at) })
                  : ""}
              </span>
            </div>
            <div className="tp-track" aria-hidden="true">
              <span style={{ width: `${Math.round(frac * 100)}%` }} />
            </div>
            {upcoming.length > 0 && (
              <div className="tp-queue">
                {upcoming.map((next, i) => (
                  <span key={i}>
                    {t("account.planQueued", {
                      plan: next.plan_title || next.plan,
                      term: f.days(next.period_days),
                      date: f.shortDate(next.starts_at),
                    })}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="ap-card">
          <div className="ap-head">
            <span className="ap-ic ap-ic-emoji">
              <TgsEmoji name="rabbit" size={62} />
            </span>
            <span className="ap-head-body">
              <span className="ap-title">{t("account.tmaPlansTitle")}</span>
              <span className="ap-sub">
                {paid ? t("account.plansHintPaid") : t("account.plansHintTrial")}
              </span>
            </span>
          </div>
        </div>

        {plans === null ? (
          <div className="sk-grid" aria-hidden="true">
            <span className="sk" style={{ height: 136 }} />
            <span className="sk" style={{ height: 136 }} />
            <span className="sk" style={{ height: 136 }} />
            <span className="sk" style={{ height: 136 }} />
          </div>
        ) : (
          <>
            <div className="tp-grid">
              {nonDaily.map((plan) => {
                const save = saveOf(plan);
                const months = plan.duration_days / 30;
                return (
                  <button
                    type="button"
                    key={plan.code}
                    className={`tp-card${selected === plan.code ? " sel" : ""}`}
                    onClick={() => {
                      setSelected(plan.code);
                      tmaHaptic("select");
                    }}
                  >
                    {(best && plan.code === best.code && save > 0) || save >= 5 ? (
                      <span
                        className={`tp-ribbon${
                          best && plan.code === best.code ? "" : " tp-ribbon-save"
                        }`}
                      >
                        <svg viewBox="0 0 84 84" aria-hidden="true">
                          <path d="M23 2 L45 2 Q54 2 60.4 8.4 L75.6 23.6 Q82 30 82 39 L82 61 Q82 70 75.6 63.6 L20.4 8.4 Q14 2 23 2 Z" />
                        </svg>
                        <b>{best && plan.code === best.code ? t("account.tmaHit") : `−${save}%`}</b>
                      </span>
                    ) : null}
                    <span className="tp-name">{plan.title}</span>
                    <span className={`tp-save${save >= 5 ? "" : " off"}`}>
                      {save >= 5
                        ? t("account.tmaSave", { pct: save })
                        : plan.code === data.plan
                          ? t("account.planCurrent")
                          : "\u00a0"}
                    </span>
                    <span className="tp-price">
                      {plan.intro_applies
                        ? f.moneyFromKopecks(plan.intro_price_kopecks, plan.currency)
                        : f.moneyFromKopecks(plan.price_kopecks, plan.currency)}
                    </span>
                    <span className="tp-month">
                      {plan.intro_applies ? (
                        /* Обычную цену показываем зачёркнутой рядом: человек
                           должен видеть, во сколько обойдётся продление, а не
                           узнавать об этом через месяц. */
                        <>
                          <s>{f.moneyFromKopecks(plan.price_kopecks, plan.currency)}</s>{" "}
                          {t("account.introThen")}
                        </>
                      ) : months >= 2 ? (
                        t("account.tmaPerMonth", {
                          price: f.moneyFromKopecks(
                            Math.round(plan.price_kopecks / months),
                            plan.currency,
                          ),
                        })
                      ) : (
                        f.days(plan.duration_days)
                      )}
                    </span>
                  </button>
                );
              })}
            </div>

            {daily && (
              <button
                type="button"
                className={`tp-card tp-daily${selected === daily.code ? " sel" : ""}`}
                onClick={() => {
                  setSelected(daily.code);
                  tmaHaptic("select");
                }}
              >
                <span className="ap-row-body">
                  <span className="tp-name">{daily.title}</span>
                  <span className="tp-month">
                    {t("account.tmaDailyPerDay", {
                      price: f.moneyFromKopecks(daily.price_kopecks, daily.currency),
                    })}
                  </span>
                </span>
                <span
                  className="tps-stepper tp-stepper"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    className="tps-step"
                    disabled={dailyDays <= 1}
                    onClick={() => setDailyDays((n) => Math.max(1, (Number(n) || 1) - 1))}
                  >
                    −
                  </button>
                  <input
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
                    className="tps-step"
                    disabled={dailyDays >= 90}
                    onClick={() => setDailyDays((n) => Math.min(90, (Number(n) || 0) + 1))}
                  >
                    +
                  </button>
                </span>
                <span className="tp-price tp-daily-total">
                  {f.moneyFromKopecks(daily.price_kopecks * (Number(dailyDays) || 1), daily.currency)}
                </span>
              </button>
            )}
          </>
        )}

        <RecurringControl onChanged={onChanged} />

        <div className="ap-rows">
          <ApRow
            icon="gift"
            title={t("account.trTitle")}
            sub={t("account.tmaTrSub", { left: f.days(data.days_left || 0) })}
            onClick={() => setTransferOpen(true)}
          />
          <ApRow
            icon="file"
            title={t("account.paymentsTitle")}
            sub={t("account.tmaPayHistSub")}
            onClick={() => setShowPayments(true)}
          />
        </div>

        {selPlan && !paying && (
          <button
            type="button"
            className="tp-cta"
            disabled={isDaily(selPlan) && !(Number(dailyDays) >= 1)}
            onClick={startPay}
          >
            {t("account.tmaContinue", {
              price: f.moneyFromKopecks(planAmountKopecks(selPlan, qty), selPlan.currency),
            })}
          </button>
        )}

        <TmaPaySheet
          open={Boolean(paying)}
          plan={paying}
          quantity={
            invoice &&
            invoice.planCode === (paying && paying.code) &&
            invoice.status === "pending"
              ? invoice.quantity || 1
              : isDaily(paying)
                ? Number(dailyDays) || 1
                : 1
          }
          busyMethod={busyMethod}
          invoice={paying && invoice && invoice.planCode === paying.code ? invoice : null}
          onPay={payWith}
          onNewInvoice={() => setInvoice(null)}
          onClose={() => {
            if (busyMethod) return;
            setPaying(null);
            // Закрыл лист сам — не открываем его снова при возврате на
            // страницу; счёт при этом продолжает ждать оплату.
            setInvoice((inv) =>
              inv && inv.status === "pending" ? { ...inv, dismissed: true } : inv,
            );
          }}
        />
        <TmaTransferSheet
          open={transferOpen}
          data={data}
          onClose={() => setTransferOpen(false)}
          onChanged={onChanged}
          onHistory={() => {
            setTransferOpen(false);
            setShowTransfers(true);
          }}
        />
        <TmaTransfersScreen open={showTransfers} onClose={() => setShowTransfers(false)} />
        <TmaPaymentsScreen
          open={showPayments}
          payments={data.payments || []}
          onClose={() => setShowPayments(false)}
        />
      </div>
    );
  }

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
                      planAmountKopecks(plan, isDaily(plan) ? dailyDays : 1),
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
