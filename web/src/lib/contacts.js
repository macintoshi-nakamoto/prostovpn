import { BRAND } from "./brand.js";

export const SUPPORT_EMAIL = BRAND.supportEmail;

// Бот — витрина и оплата (Stars, мини-приложение). Поддержка — живой
// человек в личном чате: все кнопки «написать в поддержку» ведут сюда.
export const SUPPORT_TELEGRAM = `https://t.me/${BRAND.supportBot}`;
export const SUPPORT_TELEGRAM_NAME = `@${BRAND.supportBot}`;
export const SUPPORT_CHAT = "https://t.me/temnoz";
export const SUPPORT_CHAT_NAME = "@temnoz";

export function starsPayUrl(planCode) {
  return planCode
    ? `${SUPPORT_TELEGRAM}?start=pay_${encodeURIComponent(planCode)}`
    : SUPPORT_TELEGRAM;
}

export const NEWS_TELEGRAM = `https://t.me/${BRAND.newsChannel}`;
export const NEWS_TELEGRAM_NAME = `@${BRAND.newsChannel}`;

export const SUPPORT_MAILTO = `mailto:${SUPPORT_EMAIL}`;
