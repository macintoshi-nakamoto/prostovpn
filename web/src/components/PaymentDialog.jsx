import { useEffect } from "react";
import { useI18n } from "../lib/i18n/index.jsx";
import { starsPayUrl } from "../lib/contacts.js";
import { CryptoIcon, SbpIcon, TelegramIcon } from "./PayIcons.jsx";
import "./payment-dialog.css";

export function PaymentDialog({
  open,
  plan,
  quantity = 1,

  busyMethod = null,
  invoice = null,
  onPay,
  onNewInvoice,
  onClose,
}) {
  const { t, f } = useI18n();

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !plan) return null;

  const price = f.moneyFromKopecks(plan.price_kopecks * quantity, plan.currency);
  const term = f.days(plan.duration_days * quantity);

  return (
    <div className="pay-overlay" onMouseDown={onClose}>
      <div
        className="pay"
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button className="pay-close" type="button" onClick={onClose} aria-label={t("pay.close")}>
          ✕
        </button>

        <div className="pay-head">
          <span className="pay-plan">{t("pay.title", { plan: plan.title })}</span>
          <span className="pay-sum">{price}</span>
          <span className="pay-term">{t("pay.term", { term })}</span>
        </div>

        {invoice ? (
          <PayInvoice invoice={invoice} onNewInvoice={onNewInvoice} onClose={onClose} />
        ) : (
          <>
        <div className="pay-methods">
          <PayMethod
            method="sbp"
            icon={<SbpIcon />}
            name={t("pay.sbp")}
            sub={t("pay.sbpSub")}
            busyMethod={busyMethod}
            onPay={onPay}
          />
          <PayMethod
            method="crypto"
            icon={<CryptoIcon />}
            name={t("pay.crypto")}
            sub={t("pay.cryptoSub")}
            busyMethod={busyMethod}
            onPay={onPay}
          />

          <a
            className="pay-method"
            href={starsPayUrl(plan.code)}
            target="_blank"
            rel="noreferrer"
          >
            <span className="pay-icon pay-icon-tg">
              <TelegramIcon />
            </span>
            <span className="pay-method-body">
              <span className="pay-method-name">{t("pay.stars")}</span>
              <span className="pay-method-sub">{t("pay.starsSub")}</span>
            </span>
            <span className="pay-method-go">→</span>
          </a>
        </div>

        <p className="pay-note">{t("pay.note")}</p>
          </>
        )}
      </div>
    </div>
  );
}

function PayMethod({ method, icon, name, sub, busyMethod, onPay }) {
  const { t } = useI18n();
  const isBusy = busyMethod === method;
  return (
    <button
      className="pay-method"
      type="button"

      aria-busy={isBusy}
      disabled={!onPay || (busyMethod !== null && !isBusy)}
      onClick={() => onPay(method)}
    >
      <span className={`pay-icon pay-icon-${method}`}>{icon}</span>
      <span className="pay-method-body">
        <span className="pay-method-name">{name}</span>
        <span className="pay-method-sub" aria-live="polite">
          {isBusy ? t("pay.creating") : sub}
        </span>
      </span>
      <span className="pay-method-go">→</span>
    </button>
  );
}

function PayInvoice({ invoice, onNewInvoice, onClose }) {
  const { t } = useI18n();

  if (invoice.status === "paid") {
    return (
      <div className="pay-invoice" role="status">
        <span className="pay-inv-mark ok" aria-hidden="true">
          ✓
        </span>
        <p className="pay-inv-title">{t("pay.invPaid")}</p>
        <p className="pay-inv-sub">{t("pay.invPaidSub")}</p>
        <button className="btn btn-primary pay-inv-btn" type="button" onClick={onClose}>
          {t("pay.invDone")}
        </button>
      </div>
    );
  }

  if (invoice.status === "failed") {
    return (
      <div className="pay-invoice" role="status">
        <span className="pay-inv-mark bad" aria-hidden="true">
          !
        </span>
        <p className="pay-inv-title">{t("pay.invFailed")}</p>
        <p className="pay-inv-sub">{t("pay.invFailedSub")}</p>
        <button className="btn btn-primary pay-inv-btn" type="button" onClick={onNewInvoice}>
          {t("pay.invRetry")}
        </button>
      </div>
    );
  }

  const isCrypto = invoice.method === "crypto";
  return (
    <div className="pay-invoice" role="status">
      <span className="pay-inv-pulse" aria-hidden="true" />
      <p className="pay-inv-title">{t("pay.invWaiting")}</p>
      <p className="pay-inv-sub">
        {isCrypto ? t("pay.invWaitingSubCrypto") : t("pay.invWaitingSub")}
      </p>
      <a
        className="btn btn-primary pay-inv-btn"
        href={invoice.url}
        target="_blank"
        rel="noreferrer"
      >
        {t("pay.invOpen")}
      </a>
      <p className="pay-inv-hint">
        {isCrypto ? t("pay.invHintCrypto") : t("pay.invHint")}
      </p>
      <button className="ac-link pay-inv-back" type="button" onClick={onNewInvoice}>
        {t("pay.invOther")}
      </button>
    </div>
  );
}
