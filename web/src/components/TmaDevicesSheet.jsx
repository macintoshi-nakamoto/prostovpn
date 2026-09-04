import { useState } from "react";
import { Sheet } from "./Sheet.jsx";
import { api, ApiError } from "../lib/api";
import { tmaHaptic } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Устройства: всё, что занимает место в лимите тарифа, — входы приложения,
 * ключи iPhone, ссылки для Happ, — и «Удалить» у каждого. Удаление
 * настоящее: пир и учётки снимаются с узлов, сессия отзывается.
 */

const TRASH = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
  </svg>
);

function confirmDialog(text) {
  return new Promise((resolve) => {
    try {
      const wa = window.Telegram?.WebApp;
      if (wa?.showConfirm) {
        wa.showConfirm(text, (ok) => resolve(Boolean(ok)));
        return;
      }
    } catch {}
    resolve(window.confirm(text));
  });
}

export function TmaDevicesSheet({ open, data, onClose, onChanged, onApply }) {
  const { t, f } = useI18n();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");

  const devices = data?.devices || [];
  const used = data?.devices_used ?? devices.length;

  const platform = {
    windows: "Windows",
    android: "Android",
    ios: "iOS",
    macos: "macOS",
    amnezia: "AmneziaVPN",
    happ: t("account.platformHapp"),
    web: t("account.platformWeb"),
  };

  const nameOf = (d) => {
    if (d.kind === "ios_key") return t("account.iosDeviceName", { n: d.slot });
    if (d.kind === "sub_link") return d.name || t("account.subLinkName", { n: d.slot });
    return d.name || platform[d.platform] || t("account.deviceFallback");
  };

  const remove = async (d) => {
    const ok = await confirmDialog(t("account.deviceDeleteConfirm", { name: nameOf(d) }));
    if (!ok) return;
    tmaHaptic("medium");
    setBusy(`${d.kind}-${d.id}`);
    setError("");
    try {
      if (d.kind === "ios_key") {
        onApply?.(await api.deleteIosKey(d.slot));
      } else if (d.kind === "sub_link") {
        await api.revokeSubscriptionKey(d.key_id);
        await onChanged?.();
      } else {
        await api.unlinkDevice(d.id);
        await onChanged?.();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("account.disconnectFailed"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Sheet
      open={open}
      title={t("account.tmaDevicesTitle")}
      sub={t("account.tmaDevicesLead", { used, total: data?.device_limit ?? 0 })}
      onClose={onClose}
    >
      <div className="dv">
        {devices.length === 0 ? (
          <p className="dv-empty">{t("account.devicesEmpty")}</p>
        ) : (
          devices.map((d) => {
            const id = `${d.kind}-${d.id}`;
            return (
              <div key={id} className="dv-row">
                <span className="dv-body">
                  <span className="dv-name">
                    {nameOf(d)}
                    {d.is_connected && <span className="dv-live">{t("account.deviceConnected")}</span>}
                  </span>
                  <span className="dv-sub">
                    {platform[d.platform] || d.platform || ""}
                    {d.is_current
                      ? ` · ${t("account.thisDevice")}`
                      : d.last_seen_at
                        ? ` · ${f.ago(d.last_seen_at)}`
                        : ` · ${t("account.neverConnected")}`}
                  </span>
                </span>
                {!d.is_current && (
                  <button
                    type="button"
                    className="dv-del"
                    aria-label={t("account.deviceDelete")}
                    disabled={busy === id}
                    onClick={() => remove(d)}
                  >
                    {busy === id ? "…" : TRASH}
                  </button>
                )}
              </div>
            );
          })
        )}
        {error && <p className="dv-error">{error}</p>}
        <p className="dv-hint">{t("account.tmaDevicesHint")}</p>
      </div>
    </Sheet>
  );
}
