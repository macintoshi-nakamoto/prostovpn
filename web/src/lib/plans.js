/**
 * Сумма к оплате.
 *
 * Повторяет правило из backend/app/services/orders.py:order_amount —
 * вводная цена достаётся только первой покупке и только за одну штуку.
 * Считать её здесь по-своему нельзя: витрина обещала бы одно, а счёт
 * приходил бы на другое, и человек справедливо решил бы, что его обманули.
 */
export function planAmountKopecks(plan, quantity = 1) {
  const count = Math.max(1, Number(quantity) || 1);
  if (introApplies(plan, count)) return plan.intro_price_kopecks;
  return (plan?.price_kopecks || 0) * count;
}

/** Действует ли сейчас вводная цена — по ней решаем, показывать ли «далее». */
export function introApplies(plan, quantity = 1) {
  const count = Math.max(1, Number(quantity) || 1);
  return Boolean(count === 1 && plan?.intro_applies && plan?.intro_price_kopecks > 0);
}
