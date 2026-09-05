// Профиль: всё личное и настройки в одном месте — карточка человека
// с кошельком, платежи, связь с нами, тема и язык, документы, ключ.
// Сюда переехали язык и тема из шапки: шапка теперь только «кто я» и кошелёк.

import { useState } from "react";
import { Sheet } from "./Sheet.jsx";
import WebLoginSheet from "./WebLoginSheet.jsx";
import { FaqScreen } from "./FaqScreen.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import { useTheme } from "../lib/theme.jsx";
import { isTma, tmaHaptic, tmaOpenTg } from "../lib/telegram.js";
import { LEGAL_DOCS, LEGAL_NAV } from "../lib/legal/index.js";
import { SUPPORT_CHAT } from "../lib/contacts.js";
import {
  ensureConnected,
  shortAddress,
  tonAddress,
  tonDisconnect,
  tonSetTheme,
  useTonWallet,
} from "../lib/ton.js";
import "./profile.css";

const COMMUNITY_TG = "https://t.me/+wqjcQayNFes1Yzcx";
const NEWS_TG = "https://t.me/myprostovpn";
const SUPPORT_TG = SUPPORT_CHAT;

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

// Иконки строк: залитые глифы, как в системных списках iOS — читаются
// крупнее и спокойнее, чем тонкая обводка.
const ICONS = {
  payments: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fillRule="evenodd"
        fill="currentColor"
        d="M5.2 4.8h13.6A3.2 3.2 0 0 1 22 8v8a3.2 3.2 0 0 1-3.2 3.2H5.2A3.2 3.2 0 0 1 2 16V8a3.2 3.2 0 0 1 3.2-3.2Zm-1.4 4v2.6h16.4V8.8H3.8Zm2.2 5.6a1 1 0 0 0 0 2h3.4a1 1 0 1 0 0-2H6Z"
      />
    </svg>
  ),
  password: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M8.4 9.6V7.5a3.6 3.6 0 0 1 7.2 0v2.1"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        fillRule="evenodd"
        fill="currentColor"
        d="M6.6 9.6h10.8a2.6 2.6 0 0 1 2.6 2.6v5.6a2.6 2.6 0 0 1-2.6 2.6H6.6A2.6 2.6 0 0 1 4 17.8v-5.6a2.6 2.6 0 0 1 2.6-2.6Zm5.4 3.6a1.4 1.4 0 0 0-.7 2.6v1.4a.7.7 0 0 0 1.4 0v-1.4a1.4 1.4 0 0 0-.7-2.6Z"
      />
    </svg>
  ),
  channel: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M21.3 4.3 2.9 11.2c-1 .4-1 1.1-.2 1.3l4.7 1.5 1.8 5.4c.2.6.4.8 1 .8.5 0 .7-.2 1-.5l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.5c.3-1.2-.5-1.8-1.7-1.4zM8.6 13.6l10.2-6.4c.5-.3.9-.1.6.2l-8.7 7.9-.3 3.6z"
      />
    </svg>
  ),
  community: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M9.4 4.2c-3.9 0-7 2.7-7 6 0 1.9 1 3.6 2.6 4.7l-.8 3a.6.6 0 0 0 .9.7l3.3-2c.3 0 .7.1 1 .1 3.9 0 7-2.7 7-6s-3.1-6.5-7-6.5Z"
      />
      <path
        fill="currentColor"
        d="M17.8 9.3c.1.5.2 1 .2 1.4 0 3.9-3.4 6.9-7.4 7.2 1.2 1.5 3.2 2.5 5.4 2.5.4 0 .7 0 1.1-.1l2.8 1.7a.6.6 0 0 0 .9-.7l-.7-2.5a5.5 5.5 0 0 0 2.3-4.3c0-2.5-2-4.6-4.6-5.2Z"
      />
    </svg>
  ),
  support: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fillRule="evenodd"
        fill="currentColor"
        d="M12 3.4c-5 0-9 3.4-9 7.7 0 2.5 1.4 4.7 3.5 6.1l-.9 3.4a.6.6 0 0 0 .9.7l3.7-2.3c.6.1 1.2.2 1.8.2 5 0 9-3.5 9-7.8s-4-8-9-8Zm-4.2 8a1.3 1.3 0 1 1 0 .01Zm4.2 0a1.3 1.3 0 1 1 0 .01Zm4.2 0a1.3 1.3 0 1 1 0 .01Z"
      />
      <circle cx="7.8" cy="11.2" r="1.25" fill="var(--pf-card-fill, var(--surface))" />
      <circle cx="12" cy="11.2" r="1.25" fill="var(--pf-card-fill, var(--surface))" />
      <circle cx="16.2" cy="11.2" r="1.25" fill="var(--pf-card-fill, var(--surface))" />
    </svg>
  ),
  theme: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.2" />
      <path d="M12 3v18A9 9 0 0 0 12 3Z" fill="currentColor" />
    </svg>
  ),
  language: (
    <svg viewBox="0 0 24 24" {...STROKE} aria-hidden="true">
      <circle cx="12" cy="12" r="8.6" />
      <path d="M3.4 12h17.2M12 3.4c-4.5 5-4.5 12.2 0 17.2M12 3.4c4.5 5 4.5 12.2 0 17.2" />
    </svg>
  ),
  exit: (
    <svg viewBox="0 0 24 24" {...STROKE} aria-hidden="true">
      <path d="M14.6 8V5.8a2 2 0 0 0-2-2H5.8a2 2 0 0 0-2 2v12.4a2 2 0 0 0 2 2h6.8a2 2 0 0 0 2-2V16" />
      <path d="M9.6 12h10.6M17 8.8 20.2 12 17 15.2" />
    </svg>
  ),
  wallet: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fillRule="evenodd"
        fill="currentColor"
        d="M5.4 4.6h11.8a3 3 0 0 1 3 3v.3A2.9 2.9 0 0 1 22 10.7v5.4a2.9 2.9 0 0 1-2.9 2.9h-.1a3 3 0 0 1-3 2.4H5.4a3.4 3.4 0 0 1-3.4-3.4V8a3.4 3.4 0 0 1 3.4-3.4Zm12.7 5.1h1a1.9 1.9 0 0 1 1.9 1.9v3.6a1.9 1.9 0 0 1-1.9 1.9h-1a2.9 2.9 0 0 1-2.9-2.9v-1.6a2.9 2.9 0 0 1 2.9-2.9Zm.3 2.5a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Z"
      />
    </svg>
  ),
};

function Chevron() {
  return (
    <svg className="pf-chev" viewBox="0 0 24 24" {...STROKE} aria-hidden="true">
      <path d="M9.6 6.4 15.2 12l-5.6 5.6" />
    </svg>
  );
}

// TON-эмблема для шторки кошелька — как в родных приложениях экосистемы.
export function TonBadge() {
  return (
    <svg viewBox="0 0 56 56" aria-hidden="true">
      <circle cx="28" cy="28" r="28" fill="#0098EA" />
      <path
        d="M19.1 18.6h17.8c1.7 0 2.8 1.9 2 3.4l-9.2 16.4c-.7 1.3-2.6 1.3-3.3 0l-9.2-16.4c-.9-1.5.2-3.4 1.9-3.4Zm7.2 3.2h-5.5l6 10.7V21.8h-.5Zm3.9 0v10.7l6-10.7h-6Z"
        fill="#fff"
      />
    </svg>
  );
}

function Row({ icon, label, value, onClick, danger, tinted, external }) {
  return (
    <button
      type="button"
      className={`pf-row${danger ? " pf-danger" : ""}${tinted ? " pf-tinted" : ""}${icon ? "" : " pf-noicon"}`}
      onClick={() => {
        tmaHaptic("select");
        onClick();
      }}
    >
      {icon && <span className="pf-ric">{ICONS[icon]}</span>}
      <span className="pf-label">{label}</span>
      {value && <span className="pf-value">{value}</span>}
      {external ? null : <Chevron />}
    </button>
  );
}

function openTg(url) {
  if (isTma()) tmaOpenTg(url);
  else window.open(url, "_blank", "noopener");
}

// Шторка подключённого кошелька: адрес, скопировать, отключить.
export function WalletSheet({ open, onClose }) {
  const { t } = useI18n();
  const wallet = useTonWallet();
  const [copied, setCopied] = useState(false);
  const address = tonAddress(wallet);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(address);
      tmaHaptic("light");
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  return (
    <Sheet open={open} title={t("profile.walletTitle")} sub={t("profile.walletSub")} onClose={onClose}>
      <div className="pf-wallet-badge">
        <TonBadge />
      </div>
      <div className="pf-wallet-addr">
        <span className="pf-wallet-addr-hint">{t("profile.walletYourAddress")}</span>
        <span className="pf-wallet-addr-value">{address ? shortAddress(address) : "—"}</span>
      </div>
      <button type="button" className="ap-cta" onClick={copy}>
        {copied ? t("profile.walletCopied") : t("profile.walletCopy")}
      </button>
      <button
        type="button"
        className="pf-wallet-off"
        onClick={async () => {
          await tonDisconnect();
          onClose();
        }}
      >
        {t("profile.walletDisconnect")}
      </button>
    </Sheet>
  );
}

// Платежи снизу: прошлые оплаты подписки из data.payments. Тап по строке
// копирует номер заказа — как на экране истории во вкладке «Подписка».
function PaymentsSheet({ open, payments, onClose }) {
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
    <Sheet open={open} title={t("account.paymentsTitle")} onClose={onClose}>
      {payments.length === 0 ? (
        <p className="pf-pay-empty">{t("account.paymentsEmpty")}</p>
      ) : (
        <div className="pf-pay">
          {payments.map((row, i) => (
            <button type="button" className="pf-pay-row" key={i} onClick={() => copyRow(row, i)}>
              <span className="pf-pay-body">
                <span className="pf-pay-t">{row.comment || t("account.payFallback")}</span>
                <span className="pf-pay-s">
                  {copied === i
                    ? t("account.tmaOrderCopied")
                    : `${f.longDate(row.paid_at)}${orderNo(row) ? " · " + t("account.tmaTapToCopy") : ""}`}
                </span>
              </span>
              <b className="pf-pay-sum">{f.money(row.amount, row.currency)}</b>
            </button>
          ))}
        </div>
      )}
    </Sheet>
  );
}

// Документ в шторке: те же блоки, что на полных страницах /terms и т.д.,
// только без шапки сайта — человек остаётся в кабинете.
function DocSheet({ doc, onClose }) {
  const paper = doc ? LEGAL_DOCS[doc] : null;

  return (
    <Sheet open={Boolean(paper)} title={paper?.title || ""} sub={paper?.revision} onClose={onClose}>
      {paper && (
        <div className="pf-doc">
          {paper.blocks.map((block, index) => (
            <DocBlock key={index} block={block} />
          ))}
          <p className="pf-doc-sign">{paper.footer}</p>
        </div>
      )}
    </Sheet>
  );
}

function DocBlock({ block }) {
  switch (block.type) {
    case "h2":
      return <h2>{block.text}</h2>;
    case "h3":
      return <h3>{block.text}</h3>;
    case "p":
      return <p>{block.text}</p>;
    case "note":
      return (
        <div className="pf-doc-note">
          {block.items.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      );
    case "ul":
      return (
        <ul>
          {block.items.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      );
    case "table":
      return (
        <div className="pf-doc-table">
          <table>
            <thead>
              <tr>
                {block.head.map((cell) => (
                  <th key={cell}>{cell}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row) => (
                <tr key={row[0]}>
                  {row.map((cell, i) => (
                    <td key={i}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    default:
      return null;
  }
}

export function ProfileTab({ data, tgPhoto, onPassword, onSignOut, onOpenWallet, onAdblock }) {
  const { t, lang, setLang } = useI18n();
  const { dark, setTheme } = useTheme();
  const wallet = useTonWallet();
  const [doc, setDoc] = useState(null);
  const [payOpen, setPayOpen] = useState(false);
  const [webLogin, setWebLogin] = useState(false);
  const [faqOpen, setFaqOpen] = useState(false);

  const address = tonAddress(wallet);
  const active = Boolean(data?.active);
  const initial = (data?.login || "P").slice(0, 1).toUpperCase();

  const pickTheme = (next) => {
    setTheme(next);
    tonSetTheme(next === "dark");
    tmaHaptic("select");
  };

  return (
    <div className="pf">
      <section className="pf-card pf-me">
        <div className="pf-me-top">
          <span className={`pf-ava${active ? " pf-ava-on" : ""}`}>
            {tgPhoto ? <img src={tgPhoto} alt="" referrerPolicy="no-referrer" /> : initial}
          </span>
          <span className="pf-me-body">
            <span className="pf-me-name">{data?.login || t("account.fallbackName")}</span>
            {address ? (
              <button type="button" className="pf-me-addr" onClick={onOpenWallet}>
                {shortAddress(address)}
              </button>
            ) : (
              <span className="pf-me-status">
                {active ? t("account.active") : t("account.inactive")}
              </span>
            )}
          </span>
        </div>
        {!address && (
          <button
            type="button"
            className="pf-connect"
            onClick={() => {
              tmaHaptic("select");
              ensureConnected();
            }}
          >
            {t("profile.connectTon")}
          </button>
        )}
      </section>

      <section className="pf-card">
        <Row icon="payments" label={t("profile.payments")} onClick={() => setPayOpen(true)} />
        <Row icon="password" label={t("account.webLogin")} onClick={() => setWebLogin(true)} />
        <Row icon="password" label={t("account.changePassword")} onClick={onPassword} />
      </section>

      <section className="pf-card">
        <Row icon="channel" label={t("profile.channel")} onClick={() => openTg(NEWS_TG)} />
        <Row icon="community" label={t("profile.community")} onClick={() => openTg(COMMUNITY_TG)} />
        <Row icon="support" label={t("profile.support")} onClick={() => openTg(SUPPORT_TG)} />
        <Row icon="support" label={t("profile.faq")} onClick={() => setFaqOpen(true)} />
      </section>

      <section className="pf-card">
        <div className="pf-row pf-static">
          <span className="pf-ric">{ICONS.support}</span>
          <span className="pf-label">
            {t("profile.adblock")}
            <span className="pf-sub">{t("profile.adblockSub")}</span>
          </span>
          <span
            className={`pf-seg${data?.adblock ? " pf-seg-b" : ""}`}
            role="group"
            aria-label={t("profile.adblock")}
          >
            <span className="pf-thumb" aria-hidden="true" />
            <button
              type="button"
              className={data?.adblock ? "" : "on"}
              aria-pressed={!data?.adblock}
              onClick={() => {
                tmaHaptic("select");
                onAdblock && onAdblock(false);
              }}
            >
              {t("profile.off")}
            </button>
            <button
              type="button"
              className={data?.adblock ? "on" : ""}
              aria-pressed={Boolean(data?.adblock)}
              onClick={() => {
                tmaHaptic("select");
                onAdblock && onAdblock(true);
              }}
            >
              {t("profile.on")}
            </button>
          </span>
        </div>
      </section>

      <section className="pf-card">
        <div className="pf-row pf-static">
          <span className="pf-ric">{ICONS.theme}</span>
          <span className="pf-label">{t("profile.appearance")}</span>
          <span
            className={`pf-seg${dark ? " pf-seg-b" : ""}`}
            role="group"
            aria-label={t("profile.appearance")}
          >
            <span className="pf-thumb" aria-hidden="true" />
            <button
              type="button"
              className={dark ? "" : "on"}
              aria-pressed={!dark}
              onClick={() => pickTheme("light")}
            >
              {t("profile.themeLight")}
            </button>
            <button
              type="button"
              className={dark ? "on" : ""}
              aria-pressed={dark}
              onClick={() => pickTheme("dark")}
            >
              {t("profile.themeDark")}
            </button>
          </span>
        </div>
        <div className="pf-row pf-static">
          <span className="pf-ric">{ICONS.language}</span>
          <span className="pf-label">{t("profile.language")}</span>
          <span
            className={`pf-seg${lang === "en" ? " pf-seg-b" : ""}`}
            role="group"
            aria-label={t("profile.language")}
          >
            <span className="pf-thumb" aria-hidden="true" />
            <button
              type="button"
              className={lang === "ru" ? "on" : ""}
              aria-pressed={lang === "ru"}
              onClick={() => setLang("ru")}
            >
              RU
            </button>
            <button
              type="button"
              className={lang === "en" ? "on" : ""}
              aria-pressed={lang === "en"}
              onClick={() => setLang("en")}
            >
              EN
            </button>
          </span>
        </div>
      </section>

      <section className="pf-card">
        {LEGAL_NAV.map((item) => (
          <Row
            key={item.key}
            tinted
            label={t(`profile.docs.${item.key}`)}
            onClick={() => setDoc(item.key)}
          />
        ))}
      </section>

      <section className="pf-card">
        <Row icon="exit" label={t("account.signOut")} onClick={onSignOut} danger external />
      </section>

      <WebLoginSheet open={webLogin} onClose={() => setWebLogin(false)} />
      <PaymentsSheet
        open={payOpen}
        payments={data?.payments || []}
        onClose={() => setPayOpen(false)}
      />
      <DocSheet doc={doc} onClose={() => setDoc(null)} />
      <FaqScreen open={faqOpen} onClose={() => setFaqOpen(false)} />
    </div>
  );
}
