// TON Connect: подключение кошелька и оплата заказов в TON.
//
// Один экземпляр TonConnectUI на всё приложение: SDK хранит сессию
// в localStorage и сам восстанавливает подключение после перезагрузки.
// Комментарий к переводу — id заказа: по нему вотчер на бэке находит
// оплату среди входящих транзакций кошелька-кассы.

import { useEffect, useState } from "react";
import { TonConnectUI, toUserFriendlyAddress } from "@tonconnect/ui";
import { readTheme } from "./theme.jsx";

let instance = null;

export function tonUI() {
  if (!instance) {
    instance = new TonConnectUI({
      manifestUrl: "https://prostovpn.cc/tonconnect-manifest.json",
      actionsConfiguration: {
        // Куда кошелёк возвращает человека после подписи внутри Telegram.
        twaReturnUrl: "https://t.me/prostovpnn_bot",
      },
    });
    instance.uiOptions = { uiPreferences: { theme: readTheme() === "dark" ? "DARK" : "LIGHT" } };
  }
  return instance;
}

export function tonSetTheme(dark) {
  if (!instance) return;
  instance.uiOptions = { uiPreferences: { theme: dark ? "DARK" : "LIGHT" } };
}

// Подключённый кошелёк или null. Подписка живёт, пока смонтирован компонент.
export function useTonWallet() {
  const [wallet, setWallet] = useState(() => tonUI().wallet);

  useEffect(() => tonUI().onStatusChange(setWallet), []);
  return wallet;
}

export function tonAddress(wallet) {
  const raw = wallet?.account?.address;
  if (!raw) return "";
  try {
    return toUserFriendlyAddress(raw);
  } catch {
    return raw;
  }
}

export function shortAddress(address) {
  return address.length > 12 ? `${address.slice(0, 4)}…${address.slice(-4)}` : address;
}

export async function tonDisconnect() {
  try {
    await tonUI().disconnect();
  } catch {}
}

// Открывает список кошельков и ждёт исхода: подключился человек или закрыл
// окно. Без этого «оплатить» пришлось бы жать дважды — сперва подключись,
// потом заново нажми.
export function ensureConnected() {
  const ui = tonUI();
  if (ui.connected) return Promise.resolve(true);

  return new Promise((resolve) => {
    const done = (ok) => {
      offStatus();
      offModal();
      resolve(ok);
    };
    const offStatus = ui.onStatusChange((wallet) => {
      if (wallet) done(true);
    });
    const offModal = ui.onModalStateChange((state) => {
      if (state.status === "closed") setTimeout(() => done(ui.connected), 150);
    });
    ui.openModal().catch(() => done(false));
  });
}

// Комментарий как ячейка TON: 32 нулевых бита (op текстового сообщения)
// плюс UTF-8. Ручная сборка BOC сверена побайтово с @ton/core — тащить
// саму библиотеку с Buffer-полифиллом ради одной ячейки не стали.
function commentPayload(text) {
  const data = new TextEncoder().encode(text);
  if (data.length > 100) throw new Error("комментарий длиннее одной ячейки");
  const body = new Uint8Array(4 + data.length);
  body.set(data, 4);
  const cell = new Uint8Array([0, body.length * 2, ...body]);
  const boc = new Uint8Array([
    0xb5, 0xee, 0x9c, 0x72, // магия serialized_boc
    0x01, 0x01, // размер ссылок и оффсетов — по байту
    0x01, 0x01, 0x00, // одна ячейка, один корень, absent нет
    cell.length,
    0x00, // корень — ячейка 0
    ...cell,
  ]);
  let bin = "";
  for (const byte of boc) bin += String.fromCharCode(byte);
  return btoa(bin);
}

// Бэкенд отдаёт счёт универсальной ссылкой ton://transfer/... — разбираем
// её и превращаем в запрос подписи через подключённый кошелёк.
export function parseTransferLink(url) {
  const match = /^ton:\/\/transfer\/([^?]+)\?(.*)$/.exec(url || "");
  if (!match) return null;
  const params = new URLSearchParams(match[2]);
  const amount = params.get("amount");
  if (!amount) return null;
  return { address: match[1], amount, text: params.get("text") || "" };
}

export function formatTon(nanotons) {
  const value = Number(nanotons) / 1e9;
  if (!Number.isFinite(value)) return "";
  return `${value.toFixed(value >= 10 ? 2 : 3)} TON`;
}

export async function tonPay(link) {
  const parsed = parseTransferLink(link);
  if (!parsed) throw new Error("счёт не разобрался");

  const ok = await ensureConnected();
  if (!ok) return false;

  await tonUI().sendTransaction({
    validUntil: Math.floor(Date.now() / 1000) + 15 * 60,
    messages: [
      {
        address: parsed.address,
        amount: parsed.amount,
        payload: parsed.text ? commentPayload(parsed.text) : undefined,
      },
    ],
  });
  return true;
}
