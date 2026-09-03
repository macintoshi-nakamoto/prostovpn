/*
  Бренд выбирается на этапе сборки: VITE_BRAND приходит из .env (prosto) или
  .env.rusvpn (`vite build --mode rusvpn`). Один код — два продукта:

    prosto — Prosto VPN: лендинг, вход, кабинет, гайды;
    rusvpn — Rus VPN: только кабинет (корень сразу ведёт в /account),
             свой цвет и логотип, тот же бэкенд.

  Всё, что различает продукты, лежит здесь и в styles/brand-rusvpn.css.
  Строки словарей подменяются целиком функцией brandize — новые тексты в
  ru.js/en.js можно писать с «Prosto VPN», второй бренд подставится сам.
*/

const BRANDS = {
  prosto: {
    id: "prosto",
    name: "Prosto VPN",
    domain: "prostovpn.cc",
    siteUrl: "https://prostovpn.cc",
    supportBot: "prostovpnn_bot",
    supportEmail: "support@prostovpn.cc",
    newsChannel: "myprostovpn",
    landing: true,
  },
  rusvpn: {
    id: "rusvpn",
    name: "Rus VPN",
    domain: "rusvpn.cc",
    siteUrl: "https://rusvpn.prostovpn.cc",
    // Своего бота и почты у Rus VPN пока нет — поддержка та же, что у Prosto.
    supportBot: "prostovpnn_bot",
    supportEmail: "support@prostovpn.cc",
    newsChannel: "myprostovpn",
    landing: false,
  },
};

const requested = import.meta.env.VITE_BRAND;
export const BRAND_ID = BRANDS[requested] ? requested : "prosto";
export const BRAND = BRANDS[BRAND_ID];

export function isBrand(id) {
  return BRAND_ID === id;
}

// Порядок в альтернативе важен: длинные образцы раньше коротких, иначе
// «support@prostovpn.cc» распался бы на почту с чужим доменом.
const MARKS = /support@prostovpn\.cc|@prostovpnn_bot|prostovpn\.cc|Prosto ?VPN|prosto_user/g;

export function brandText(text) {
  if (BRAND_ID === "prosto" || typeof text !== "string") return text;
  return text.replace(MARKS, (mark) => {
    if (mark === "support@prostovpn.cc") return BRAND.supportEmail;
    if (mark === "@prostovpnn_bot") return `@${BRAND.supportBot}`;
    if (mark === "prostovpn.cc") return BRAND.domain;
    if (mark === "prosto_user") return `${BRAND.id}_user`;
    return BRAND.name;
  });
}

// Глубокая подмена по словарю: строки, массивы, вложенные объекты.
export function brandize(node) {
  if (BRAND_ID === "prosto") return node;
  if (typeof node === "string") return brandText(node);
  if (Array.isArray(node)) return node.map(brandize);
  if (node && typeof node === "object") {
    const out = {};
    for (const key of Object.keys(node)) out[key] = brandize(node[key]);
    return out;
  }
  return node;
}
