import { api, escapeHtml, moneyParts, plural, term } from "./api.js";

const holder = document.getElementById("plans");

function planRow(plan) {
  const price = moneyParts(plan.price_kopecks, plan.currency);
  const perMonth =
    plan.duration_days >= 60
      ? moneyParts(Math.round(plan.price_kopecks / (plan.duration_days / 30)), plan.currency)
      : null;

  const note =
    plan.tagline ||
    `${plan.server_limit} ${plural(plan.server_limit, "страна", "страны", "стран")} · ` +
      `${plan.device_limit} ${plural(plan.device_limit, "устройство", "устройства", "устройств")}`;

  return `
    <a class="plan" href="checkout.html?plan=${encodeURIComponent(plan.code)}">
      <div>
        <div class="plan-name">${escapeHtml(plan.title)}</div>
        <div class="plan-term">${escapeHtml(term(plan.duration_days))} доступа</div>
      </div>
      <div class="plan-note">${escapeHtml(note)}</div>
      <div class="plan-right">
        <div>
          <div class="plan-price">${price.value} ${price.sign}</div>
          ${perMonth ? `<div class="plan-per-month">${perMonth.value} ${perMonth.sign} в месяц</div>` : ""}
        </div>
        <span class="plan-go" aria-hidden="true">→</span>
      </div>
    </a>`;
}

async function render() {
  if (!holder) return;
  try {
    const plans = (await api.plans()).filter((plan) => plan.purchasable !== false);
    if (!plans.length) {
      holder.innerHTML =
        '<p class="muted" style="padding:28px 0">Тарифы временно недоступны. Напишите нам — подберём вручную.</p>';
      return;
    }
    holder.innerHTML = plans.map(planRow).join("");
  } catch (error) {
    holder.innerHTML = `<p class="muted" style="padding:28px 0">${escapeHtml(error.message)}</p>`;
  }
}

render();
