export const SUPPORT_EMAIL = "support@prostovpn.cc";

export const SUPPORT_TELEGRAM = "https://t.me/prostovpnn_bot";
export const SUPPORT_TELEGRAM_NAME = "@prostovpnn_bot";

export function starsPayUrl(planCode) {
  return planCode
    ? `${SUPPORT_TELEGRAM}?start=pay_${encodeURIComponent(planCode)}`
    : SUPPORT_TELEGRAM;
}

export const NEWS_TELEGRAM = "https://t.me/myprostovpn";
export const NEWS_TELEGRAM_NAME = "@myprostovpn";

export const SUPPORT_MAILTO = `mailto:${SUPPORT_EMAIL}`;
