import { api, money, term } from "./api.js";

const orderId = new URLSearchParams(location.search).get("order");
const payButton = document.getElementById("pay");
const errorBox = document.getElementById("error");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

async function load() {
  if (!orderId) {
    showError("Заказ не указан. Начните с выбора тарифа.");
    payButton.disabled = true;
    return;
  }

  document.getElementById("order-id").textContent = orderId.slice(0, 8);

  let status;
  try {
    status = await api.orderStatus(orderId);
  } catch (error) {
    showError(error.message);
    payButton.disabled = true;
    return;
  }

  if (status.status === "paid") {
    location.replace(`success.html?order=${encodeURIComponent(orderId)}`);
    return;
  }

  document.getElementById("email").textContent = status.email || "почту из заказа";

  document.getElementById("amount").textContent = money(status.amount_kopecks, status.currency);

  try {
    const plans = await api.plans();
    const plan = plans.find((item) => item.code === status.plan_code);
    if (plan) {
      document.getElementById("plan-note").textContent = `${plan.title} · ${term(
        plan.duration_days,
      )} доступа`;
    }
  } catch {}
}

payButton.addEventListener("click", async () => {
  showError("");
  payButton.disabled = true;
  payButton.textContent = "Проводим оплату…";

  try {
    await api.mockPay(orderId);
  } catch (error) {
    showError(error.message);
    payButton.disabled = false;
    payButton.textContent = "Оплатить";
    return;
  }

  location.href = `success.html?order=${encodeURIComponent(orderId)}`;
});

load();
