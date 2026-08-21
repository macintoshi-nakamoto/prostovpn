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
export function PaymentDialog({ open, plan, busy = false, onSbp, onClose }) {
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

  const price = f.moneyFromKopecks(plan.price_kopecks, plan.currency);
  const term = f.days(plan.duration_days);

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

        <p className="pay-note">{t("pay.note")}</p>
      </div>
    </div>
  );
}
