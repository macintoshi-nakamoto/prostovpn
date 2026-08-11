/* Личный кабинет.

   Показывает срок, устройства и кнопку продления. Ключей и конфигураций
   здесь нет — их нет вообще нигде, куда смотрит человек: приложение
   получает всё, что нужно, само, а вопрос «а куда это вставить» не должен
   возникнуть ни разу за жизнь подписки.

   Продление оформляется обычным заказом и идёт через ту же оплату и тот же
   вебхук. Отдельного «продлить одной кнопкой» в обход платежа нет: он
   прошёл бы мимо сверки суммы и идемпотентности, то есть мимо всего, ради
   чего оплата устроена так, как устроена. */

import { api, escapeHtml, formatDate, getToken, plural, setToken } from "./api.js";

const views = {
  loading: document.getElementById("loading-view"),
  login: document.getElementById("login-view"),
  account: document.getElementById("account-view"),
};

function show(name) {
  for (const [key, node] of Object.entries(views)) node.hidden = key !== name;
}

function setError(id, message) {
  const box = document.getElementById(id);
  box.textContent = message || "";
  box.hidden = !message;
}

/* ── Вход ──────────────────────────────────────────────────────────────── */

const loginForm = document.getElementById("login-form");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("login-error", "");

  const login = document.getElementById("login").value.trim();
  const password = document.getElementById("password").value;
  if (!login || !password) {
    setError("login-error", "Введите логин и пароль из письма.");
    return;
  }

  const button = document.getElementById("login-submit");
  button.disabled = true;
  button.textContent = "Входим…";

  try {
    const result = await api.login({
      login,
      password,
      platform: "web",
      // Кабинет — не устройство: он не занимает место в лимите тарифа, и
      // помечен так, чтобы это было видно в списке.
      device_id: "web-account",
      device_name: "Личный кабинет",
    });
    setToken(result.token);
    await loadAccount();
  } catch (error) {
    setError("login-error", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Войти";
  }
});

/* ── Кабинет ───────────────────────────────────────────────────────────── */

let account = null;

function renderDevices() {
  const holder = document.getElementById("devices");
  const devices = account.devices || [];

  document.getElementById("devices-note").textContent =
    `Занято ${devices.length} из ${account.device_limit}. ` +
    "Если войти с нового устройства сверх лимита, самое старое отключится.";

  if (!devices.length) {
    holder.innerHTML = '<p class="muted" style="margin:0">Ни одного входа пока не было.</p>';
    return;
  }

  holder.innerHTML = devices
    .map((device) => {
      const name = device.name || platformName(device.platform);
      const version = device.app_version ? ` · ${escapeHtml(device.app_version)}` : "";
      return `
        <div class="device">
          <div style="min-width:0">
            <div style="font-weight:600">${escapeHtml(name)}${
              device.is_current ? ' <span class="badge">это устройство</span>' : ""
            }</div>
            <div class="dl-meta">${escapeHtml(formatDate(device.last_seen_at))}${version}</div>
          </div>
          <button
            class="copy"
            type="button"
            style="margin-left:auto"
            data-unlink="${device.id}"
          >Отвязать</button>
        </div>`;
    })
    .join("");
}

function platformName(platform) {
  return (
    { windows: "Windows", android: "Android", ios: "iPhone", macos: "Mac", linux: "Linux", web: "Браузер" }[
      platform
    ] || "Устройство"
  );
}

function renderAccount() {
  document.getElementById("greeting").textContent = account.active
    ? "Доступ активен"
    : "Доступ приостановлен";

  document.getElementById("a-login").textContent = account.login;
  document.getElementById("a-plan").textContent = account.plan_title || account.plan || "—";
  document.getElementById("a-expires").textContent = account.expires_at
    ? formatDate(account.expires_at)
    : "—";

  const state = document.getElementById("a-state");
  if (account.active) {
    const left = account.days_left ?? 0;
    state.textContent = `осталось ${left} ${plural(left, "день", "дня", "дней")}`;
    state.className = left <= 5 ? "badge badge-warn" : "badge badge-ok";
  } else {
    state.textContent = "не оплачен";
    state.className = "badge badge-warn";
  }

  renderDevices();
  show("account");
}

async function loadAccount() {
  if (!getToken()) {
    show("login");
    return;
  }
  show("loading");
  try {
    account = await api.account();
    renderAccount();
  } catch (error) {
    if (error.status === 401) {
      setToken(null);
      show("login");
      return;
    }
    setError("account-error", error.message);
    show("account");
  }
}

/* ── Действия ──────────────────────────────────────────────────────────── */

document.getElementById("devices").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-unlink]");
  if (!button) return;

  button.disabled = true;
  setError("account-error", "");
  try {
    await api.unlinkDevice(Number(button.getAttribute("data-unlink")));
    account = await api.account();
    renderDevices();
  } catch (error) {
    if (error.status === 401) {
      // Отвязали устройство, с которого сидим — это нормально и ожидаемо.
      setToken(null);
      show("login");
      return;
    }
    setError("account-error", error.message);
    button.disabled = false;
  }
});

document.getElementById("renew").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Создаём заказ…";
  setError("account-error", "");

  try {
    const order = await api.renew(account.plan);
    if (!order.redirect_url) throw new Error("Платёжная форма недоступна. Попробуйте позже.");
    sessionStorage.setItem("prosto.order", order.id);
    location.href = order.redirect_url;
  } catch (error) {
    setError("account-error", error.message);
    button.disabled = false;
    button.textContent = "Продлить доступ";
  }
});

document.getElementById("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("password-error", "");

  const current = document.getElementById("old-password").value;
  const next = document.getElementById("new-password").value;
  if (next.length < 8) {
    setError("password-error", "Новый пароль короче восьми символов.");
    return;
  }

  const button = document.getElementById("password-submit");
  button.disabled = true;
  button.textContent = "Меняем…";

  try {
    await api.changePassword({ current_password: current, new_password: next });
    // Смена пароля гасит все сессии, включая эту, — это и есть смысл.
    setToken(null);
    alert("Пароль изменён. Войдите заново — здесь и в приложении.");
    location.reload();
  } catch (error) {
    setError("password-error", error.message);
    button.disabled = false;
    button.textContent = "Сменить пароль";
  }
});

document.getElementById("logout").addEventListener("click", (event) => {
  event.preventDefault();
  setToken(null);
  location.reload();
});

document.getElementById("logout").hidden = !getToken();

loadAccount();
