/*
 * Куда писать. Одно место на весь сайт.
 *
 * Адреса разъезжаются быстрее всего: почта появилась позже телеграма, и
 * дописывать её пришлось бы в футер, контакты, FAQ и инструкцию по отдельности
 * — а через месяц выяснилось бы, что где-то остался прежний ящик.
 */

/** Ящик поддержки: на него отвечают люди, его же показываем в письмах. */
export const SUPPORT_EMAIL = "support@prostovpn.cc";

/**
 * Бот в Telegram — он же поддержка.
 *
 * Он оформляет подписку, отдаёт доступ и принимает вопросы: одно окно на всё,
 * человеку не приходится выбирать, куда писать.
 */
export const SUPPORT_TELEGRAM = "https://t.me/prostovpnn_bot";
export const SUPPORT_TELEGRAM_NAME = "@prostovpnn_bot";

/** Канал с новостями. Читают, а не пишут. */
export const NEWS_TELEGRAM = "https://t.me/myprostovpn";
export const NEWS_TELEGRAM_NAME = "@myprostovpn";

export const SUPPORT_MAILTO = `mailto:${SUPPORT_EMAIL}`;
