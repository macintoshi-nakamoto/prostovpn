import { terms } from "./terms.js";
import { privacy } from "./privacy.js";
import { aup } from "./aup.js";
import { refund } from "./refund.js";
import { licenses } from "./licenses.js";

/*
 * Пять документов и их адреса.
 *
 * Адреса зашиты в самих текстах («действующая редакция размещена по
 * адресу…»), поэтому маршруты обязаны им соответствовать: документ, который
 * ссылается сам на себя мимо, выглядит подделкой.
 */
export const LEGAL_DOCS = { terms, privacy, aup, refund, licenses };

export const LEGAL_NAV = [
  { key: "terms", path: "/terms", label: "Публичная оферта" },
  { key: "privacy", path: "/privacy", label: "Конфиденциальность" },
  { key: "aup", path: "/aup", label: "Правила использования" },
  { key: "refund", path: "/refund", label: "Возвраты" },
  { key: "licenses", path: "/licenses", label: "Лицензии" },
];
