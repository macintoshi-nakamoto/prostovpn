import { useEffect } from "react";
import { useI18n } from "../lib/i18n/index.jsx";
import { starsPayUrl } from "../lib/contacts.js";
import { CryptoIcon, SbpIcon, TelegramIcon } from "./PayIcons.jsx";
import "./payment-dialog.css";

/**
 * Выбор способа оплаты.
 *
 * СБП и криптовалюта — настоящая оплата: панель создаёт заказ и уводит на
 * платёжную форму провайдера, оба способа идут через одного провайдера и
 * различаются только кодом метода. Telegram Stars живут в боте (ссылка
 * ведёт в того же бота, что и поддержка, — одно окно на всё, см.
 * contacts.js).
 *
 * Порядок в ряду — по тому, как далеко уводит способ: СБП и криптовалюта
 * платятся на месте, Telegram уходит из браузера.
 *
 * Анимация — только `opacity` и `transform`: их браузер считает на
 * видеокарте, окно открывается плавно даже на слабом телефоне. Тем, кто
 * просил в системе меньше движения, окно появляется без него совсем.
 */
export function PaymentDialog({
  open,
  plan,
  quantity = 1,
  // Какой способ сейчас создаёт заказ, или null. Не общий флаг: пока занята
  // одна строка, остальные обязаны показывать, что заняты не они.
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
          {/* Оба способа платятся на месте: заказ в панели и платёжная форма
              провайдера. Пока строка создаёт заказ, нажать её повторно
              нельзя — второй клик наплодил бы заказов. */}
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

          {/* Telegram Stars — не наш заказ, а бот: ссылка уводит из браузера,
              поэтому строка стоит последней и остаётся ссылкой, а не кнопкой. */}
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

/*
Строка способа, который платится на месте.

Одна форма на СБП и криптовалюту: они различаются только знаком, словами и
кодом метода, а ведут себя одинаково. Когда заказ создаётся, занята ровно
нажатая строка — она же и объясняет, что происходит; соседние просто
недоступны, но не притворяются работающими.
*/
function PayMethod({ method, icon, name, sub, busyMethod, onPay }) {
  const { t } = useI18n();
  const isBusy = busyMethod === method;
  return (
    <button
      className="pay-method"
      type="button"
      /*
      Занятая строка НЕ становится disabled, а только помечается aria-busy.
      Причина простая: disabled-элемент нельзя держать в фокусе, и браузер
      сбрасывал фокус с только что нажатой кнопки на body — человек с
      клавиатуры терял место, как раз когда начиналось ожидание. Повторное
      нажатие безвредно: payWith выходит сразу, пока способ занят.
      */
      aria-busy={isBusy}
      disabled={!onPay || (busyMethod !== null && !isBusy)}
      onClick={() => onPay(method)}
    >
      <span className={`pay-icon pay-icon-${method}`}>{icon}</span>
      <span className="pay-method-body">
        <span className="pay-method-name">{name}</span>
        {/* Подпись меняется на «Создаём счёт…» — это единственный признак
            работы, поэтому его надо и произнести, а не только показать. */}
        <span className="pay-method-sub" aria-live="polite">
          {isBusy ? t("pay.creating") : sub}
        </span>
      </span>
      <span className="pay-method-go">→</span>
    </button>
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

  // Слова зависят от способа: платёж по СБП подтверждает банк за секунды, а
  // перевод в сети идёт своим ходом и ждать его приходится дольше. Общий
  // текст про «банк» и «около 30 минут» для криптовалюты был бы неправдой.
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
      {/* Дорога назад к списку способов. Без неё человек, выбравший
          криптовалюту и передумавший, оставался заперт в этом окне до
          истечения счёта: ряд способов подменён ожиданием, а кнопка нового
          счёта есть только у неоплаченного. Сервер к смене способа готов —
          он заводит на другой способ отдельный заказ. */}
      <button className="ac-link pay-inv-back" type="button" onClick={onNewInvoice}>
        {t("pay.invOther")}
      </button>
    </div>
  );
}
