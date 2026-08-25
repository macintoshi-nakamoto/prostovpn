import { api, escapeHtml, formatDate } from "./api.js";

const WAIT_LIMIT_MS = 90_000;
const FIRST_DELAY_MS = 1200;
const MAX_DELAY_MS = 5000;

const views = {
  waiting: document.getElementById("waiting"),
  done: document.getElementById("done"),
  slow: document.getElementById("slow"),
  failed: document.getElementById("failed"),
};

const orderId =
  new URLSearchParams(location.search).get("order") || sessionStorage.getItem("prosto.order");

function show(name) {
  for (const [key, node] of Object.entries(views)) node.hidden = key !== name;
}

function fail(title, text) {
  document.getElementById("failed-title").textContent = title;
  document.getElementById("failed-text").textContent = text;
  show("failed");
}

function fillCredentials(status) {
  const renewal = status.is_renewal;

  document.getElementById("done-title").textContent = renewal
    ? "Подписка продлена"
    : "Доступ готов";
  document.getElementById("done-sub").textContent = renewal
    ? "Логин и пароль прежние — на устройствах ничего менять не нужно."
    : "Сохраните эти две строки — их нужно ввести в приложении один раз.";

  const login = document.getElementById("login");
  login.textContent = status.login || "—";
  document.getElementById("copy-login").setAttribute("data-copy", status.login || "");

  const passwordRow = document.getElementById("password-row");
  if (status.password) {
    document.getElementById("password").textContent = status.password;
    document.getElementById("copy-password").setAttribute("data-copy", status.password);
    passwordRow.hidden = false;
  } else {
    passwordRow.hidden = true;
  }

  document.getElementById("expires").textContent = status.expires_at
    ? `Действует до ${formatDate(status.expires_at)}`
    : "";

  document.getElementById("email-note").innerHTML = status.email
    ? escapeHtml(status.email)
    : "указанную при оплате";

  show("done");
}

async function poll() {
  if (!orderId) {
    fail("Заказ не найден", "Похоже, вы открыли эту страницу напрямую. Начните с выбора тарифа.");
    return;
  }

  document.getElementById("order-id").textContent = orderId;

  const startedAt = Date.now();
  let delay = FIRST_DELAY_MS;

  while (Date.now() - startedAt < WAIT_LIMIT_MS) {
    let status;
    try {
      status = await api.orderStatus(orderId);
    } catch (error) {
      if (error.status === 404) {
        fail("Заказ не найден", "Проверьте ссылку из письма или напишите нам.");
        return;
      }

      await sleep(delay);
      delay = Math.min(delay * 1.4, MAX_DELAY_MS);
      continue;
    }

    if (status.status === "paid") {
      sessionStorage.removeItem("prosto.order");
      fillCredentials(status);
      return;
    }

    if (status.status === "failed") {
      fail(
        "Платёж не прошёл",
        "Платёжный сервис отклонил оплату. Деньги не списаны — можно попробовать ещё раз.",
      );
      return;
    }

    if (status.status === "expired") {
      fail("Заказ устарел", "С момента оформления прошло больше суток. Оформите новый — это быстро.");
      return;
    }

    if (status.status === "refunded") {
      fail("По заказу оформлен возврат", "Если это не вы — напишите нам, разберёмся.");
      return;
    }

    await sleep(delay);
    delay = Math.min(delay * 1.25, MAX_DELAY_MS);
  }

  show("slow");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

document.getElementById("retry").addEventListener("click", () => {
  show("waiting");
  poll();
});

poll();
