import { BRAND } from "./brand.js";

export const SUPPORT_EMAIL = BRAND.supportEmail;

export const SUPPORT_TELEGRAM = `https://t.me/${BRAND.supportBot}`;
export const SUPPORT_TELEGRAM_NAME = `@${BRAND.supportBot}`;

export function starsPayUrl(planCode) {
  return planCode
    ? `${SUPPORT_TELEGRAM}?start=pay_${encodeURIComponent(planCode)}`
    : SUPPORT_TELEGRAM;
}

export const NEWS_TELEGRAM = `https://t.me/${BRAND.newsChannel}`;
export const NEWS_TELEGRAM_NAME = `@${BRAND.newsChannel}`;

export const SUPPORT_MAILTO = `mailto:${SUPPORT_EMAIL}`;
