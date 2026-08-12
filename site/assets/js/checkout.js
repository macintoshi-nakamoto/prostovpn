/* Оформление заказа.

   Единственная задача страницы — создать заказ и отправить человека на
   платёжную форму. Ничего «выдающего» здесь не происходит и не может: до
   вебхука провайдера заказ остаётся неоплаченным, сколько бы раз эту
   страницу ни открыли. */

import { api, escapeHtml, money, term } from "./api.js";

const select = document.getElementById("plan");
const priceEl = document.getElementById("price");
const priceNote = document.getElementById("price-note");
const form = document.getElementById("form");
const emailInput = document.getElementById("email");
const telegramInput = document.getElementById("telegram");
const submit = document.getElementById("submit");
const errorBox = document.getElementById("error");

let plans = [];

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function currentPlan() {
  return plans.find((plan) => plan.code === select.value) || null;
}

function paint() {
  const plan = currentPlan();
  if (!plan) return;
  priceEl.textContent = money(plan.price_kopecks, plan.currency);
  priceNote.textContent = `за ${term(plan.duration_days)}`;
}

async function load() {
  try {
    plans = await api.plans();
  } catch (error) {
    showError(error.message);
    select.innerHTML = "<option>Не загрузилось</option>";
    submit.disabled = true;
    return;
  }

  if (!plans.length) {
    showError("Тарифы временно недоступны. Напишите нам — подберём вручную.");
    submit.disabled = true;
    return;
  }

  select.innerHTML = plans
    .map(
      (plan) =>
        `<option value="${escapeHtml(plan.code)}">${escapeHtml(plan.title)} — ${money(
          plan.price_kopecks,
          plan.currency,
        )} за ${escapeHtml(term(plan.duration_days))}</option>`,
    )
    .join("");

  // Тариф из ссылки на главной: человек уже выбрал его там, и заставлять
  // выбирать второй раз — терять его на ровном месте.
  const wanted = new URLSearchParams(location.search).get("plan");
  if (wanted && plans.some((plan) => plan.code === wanted)) select.value = wanted;

  paint();
}

select.addEventListener("change", paint);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");

  const email = emailInput.value.trim();
  if (!email || !/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(email)) {
    showError("Проверьте адрес почты — на него придёт доступ.");
    emailInput.focus();
    return;
  }

  const telegramRaw = telegramInput.value.trim();
  if (telegramRaw && !/^\d{5,15}$/.test(telegramRaw)) {
    showError("Telegram ID — это число. Если не знаете своего, оставьте поле пустым.");
    telegramInput.focus();
    return;
  }

  submit.disabled = true;
  submit.textContent = "Создаём заказ…";

  try {
    const order = await api.createOrder({
      plan_code: select.value,
      email,
      telegram_id: telegramRaw ? Number(telegramRaw) : null,
    });

    if (!order.redirect_url) {
      throw new Error("Платёжная форма недоступна. Попробуйте позже или напишите нам.");
    }

    // Номер заказа — в адресной строке страницы успеха. Провайдер вернёт
    // человека туда же, но полагаться на это нельзя: он может закрыть
    // вкладку с оплатой и вернуться в эту.
    sessionStorage.setItem("prosto.order", order.id);
    location.href = order.redirect_url;
  } catch (error) {
    showError(error.message);
    submit.disabled = false;
    submit.textContent = "Перейти к оплате";
  }
});

load();
