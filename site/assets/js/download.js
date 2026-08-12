/* Ссылки на установщики.

   Версии и адреса приходят из панели: раздел «Версии» — единственное место,
   где они задаются, и ссылка в вёрстке протухла бы к первому же обновлению
   приложения.

   Платформа посетителя определяется и ставится первой. Не для красоты:
   человек с телефона не должен искать свою строку среди четырёх. */

import { api, escapeHtml } from "./api.js";

const holder = document.getElementById("downloads");

const PLATFORMS = [
  { id: "windows", name: "Windows", hint: "Windows 10 и новее" },
  { id: "android", name: "Android", hint: "Android 8 и новее" },
  { id: "ios", name: "iPhone и iPad", hint: "iOS 15 и новее" },
  { id: "macos", name: "macOS", hint: "macOS 12 и новее" },
];

function guessPlatform() {
  const ua = navigator.userAgent;
  if (/Android/i.test(ua)) return "android";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  if (/Mac OS X/i.test(ua)) return "macos";
  if (/Windows/i.test(ua)) return "windows";
  return null;
}

function size(bytes) {
  if (!bytes) return "";
  const mb = bytes / 1024 / 1024;
  return mb >= 1 ? ` · ${mb.toFixed(0)} МБ` : ` · ${(bytes / 1024).toFixed(0)} КБ`;
}

function card(platform, release) {
  const meta = release
    ? `Версия ${escapeHtml(release.version)}${size(release.size_bytes)}`
    : "Скоро";

  const attrs = release
    ? `href="${escapeHtml(release.url)}" download`
    : 'href="#" aria-disabled="true" tabindex="-1"';

  return `
    <a class="dl" id="${platform.id}" ${attrs}>
      <div>
        <div class="dl-name">${escapeHtml(platform.name)}</div>
        <div class="dl-meta">${meta} · ${escapeHtml(platform.hint)}</div>
      </div>
      <span style="margin-left:auto;color:var(--accent)" aria-hidden="true">↓</span>
    </a>`;
}

async function render() {
  if (!holder) return;

  let releases = [];
  try {
    releases = await api.downloads();
  } catch {
    // Ссылок нет — но инструкция ниже по странице всё равно полезна, и
    // ронять из-за этого весь экран не стоит.
    releases = [];
  }

  const byPlatform = new Map(releases.map((release) => [release.platform, release]));

  const mine = guessPlatform();
  const ordered = [...PLATFORMS].sort((a, b) => (a.id === mine ? -1 : b.id === mine ? 1 : 0));

  holder.innerHTML = ordered
    .map((platform) => card(platform, byPlatform.get(platform.id)))
    .join("");

  if (!releases.length) {
    holder.insertAdjacentHTML(
      "afterend",
      '<p class="field-hint" style="margin-top:16px">Ссылки на установщики появятся здесь, ' +
        'как только выйдет сборка. <a href="contacts.html" class="accent">Напишите нам</a>, ' +
        "и мы пришлём её лично.</p>",
    );
  }
}

render();
