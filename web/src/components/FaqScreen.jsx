import { ScreenShell } from "./ScreenShell.jsx";
import { FaqList } from "./FaqList.jsx";
import { isTma } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";
import { SUPPORT_TELEGRAM } from "../lib/contacts.js";

/**
 * «Вопросы и ответы» внутри кабинета — полноэкранная страница поверх
 * профиля. В Telegram её закрывает системная кнопка «назад» (стек
 * pushBack внутри ScreenShell), в браузере — своя стрелка в шапке.
 */
export function FaqScreen({ open, onClose }) {
  const { t } = useI18n();

  return (
    <ScreenShell open={open} title={t("faq.title")} back={!isTma()} onClose={onClose}>
      <div className="fq-screen">
        <p className="fq-screen-lead">{t("faq.lead")}</p>
        <FaqList compact />
        <div className="fq-screen-cta">
          <span>{t("faq.notFound")}</span>
          <a className="ap-cta" href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
            {t("faq.write")}
          </a>
        </div>
      </div>
    </ScreenShell>
  );
}
