import { useEffect } from "react";
import { useI18n } from "../lib/i18n/index.jsx";
import { SUPPORT_TELEGRAM } from "../lib/contacts.js";
import { CryptoIcon, SbpIcon, TelegramIcon } from "./PayIcons.jsx";
import "./payment-dialog.css";

/**
 * Выбор способа оплаты.
 *
 * СБП — настоящая оплата: панель создаёт заказ и уводит на платёжную
 * форму провайдера. Telegram Stars живут в боте (ссылка ведёт в того же
 * бота, что и поддержка, — одно окно на всё, см. contacts.js), а способ со
 * словом «скоро» нажать нельзя: лучше честная пометка, чем пустая форма.
 *
 * Анимация — только `opacity` и `transform`: их браузер считает на
 * видеокарте, окно открывается плавно даже на слабом телефоне. Тем, кто
 * просил в системе меньше движения, окно появляется без него совсем.
 */
export function PaymentDialog({
  open,
  plan,
  quantity = 1,
  busy = false,
  invoice = null,
  canAutoRenew = true,
  autoRenew = true,
  onAutoRenew,
  onSbp,
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

  // Посуточный берут пачкой дней: и цена, и срок в шапке — за выбранное
  // количество, иначе окно оплаты показывало бы одно, а списалось бы другое.
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
          <a className="pay-method pay-tg" href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
            <span className="pay-icon pay-icon-tg">
              <TelegramIcon />
            </span>
            <span className="pay-method-body">
              <span className="pay-method-name">{t("pay.stars")}</span>
              <span className="pay-method-sub">{t("pay.starsSub")}</span>
            </span>
            <span className="pay-method-go">→</span>
          </a>

          {/* СБП — настоящая оплата: заказ в панели и платёжная форма
              провайдера. Пока заказ создаётся, окно закрыть нельзя — повторный
              клик наплодил бы заказов. */}
          <button
            className="pay-method"
            type="button"
            disabled={!onSbp || busy}
            onClick={onSbp}
          >
            <span className="pay-icon">
              <SbpIcon />
            </span>
            <span className="pay-method-body">
              <span className="pay-method-name">{t("pay.sbp")}</span>
              <span className="pay-method-sub">
                {busy ? t("pay.sbpBusy") : t("pay.sbpSub")}
              </span>
            </span>
            <span className="pay-method-go">→</span>
          </button>

          <button className="pay-method" type="button" disabled>
            <span className="pay-icon">
              <CryptoIcon />
            </span>
            <span className="pay-method-body">
              <span className="pay-method-name">{t("pay.crypto")}</span>
              <span className="pay-method-sub">{t("pay.soonSub")}</span>
            </span>
            <span className="pay-method-soon">{t("pay.soon")}</span>
          </button>
        </div>

        {/* Автопродление — по умолчанию включено: подписку берут, чтобы она
            не обрывалась. Галочка на виду, снимается тем же кликом. На
            тарифах, где автосписания не бывает, её нет вовсе: обещать
            подключение, которое не состоится, хуже, чем промолчать. */}
        {canAutoRenew && (
        <label className="pay-auto">
          <input
            type="checkbox"
            checked={autoRenew}
            onChange={(e) => onAutoRenew && onAutoRenew(e.target.checked)}
          />
          <span>
            <b>{t("pay.autoTitle")}</b>
            <span className="pay-auto-sub">{t("pay.autoSub")}</span>
          </span>
        </label>
        )}

        <p className="pay-note">{t("pay.note")}</p>
          </>
        )}
      </div>
    </div>
  );
}

/*
Состояние выставленного счёта. Страница оплаты открыта в соседней вкладке,
а это окно живёт своей жизнью: опрос статуса ведёт вкладка тарифов, здесь
только отражение — ждём, оплачено, истекло. Кнопка-ссылка обязательна:
блокировщик всплывающих окон мог не пустить автоматическое открытие.
*/
function PayInvoice({ invoice, onNewInvoice, onClose }) {
  const { t } = useI18n();

  if (invoice.status === "paid") {
    return (
      <div className="pay-invoice">
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
      <div className="pay-invoice">
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

  return (
    <div className="pay-invoice">
      <span className="pay-inv-pulse" aria-hidden="true" />
      <p className="pay-inv-title">{t("pay.invWaiting")}</p>
      <p className="pay-inv-sub">{t("pay.invWaitingSub")}</p>
      <a
        className="btn btn-primary pay-inv-btn"
        href={invoice.url}
        target="_blank"
        rel="noreferrer"
      >
        {t("pay.invOpen")}
      </a>
      <p className="pay-inv-hint">{t("pay.invHint")}</p>
    </div>
  );
}
