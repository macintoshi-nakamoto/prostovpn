import { useEffect, useState } from "react";
import { KeyRound, ShieldCheck, ShieldOff } from "lucide-react";
import { authApi } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { Button, Card, Chip, QrCode } from "../../ui";

/**
 * Второй фактор для входа в панель.
 *
 * Пока не включён — карточка зовёт включить: пароль администратора один
 * на всех, а панель торчит в интернет. Включение — по коду из приложения,
 * чтобы не запереть себя секретом, который не сохранился. Выключение —
 * тоже по коду: украденной сессии этого не хватит.
 */
export function TotpCard() {
  const [status, setStatus] = useState(null);
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("idle"); // idle | enabling | disabling

  const load = () =>
    authApi
      .totp()
      .then(setStatus)
      .catch(() => setStatus({ enabled: false }));

  useEffect(() => {
    load();
  }, []);

  const begin = async () => {
    setBusy(true);
    setError("");
    try {
      setSetup(await authApi.totpSetup());
      setMode("enabling");
      setCode("");
    } catch (err) {
      setError(err.message || "Не вышло");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      const next = mode === "enabling" ? await authApi.totpEnable(code) : await authApi.totpDisable(code);
      setStatus(next);
      setSetup(null);
      setMode("idle");
      setCode("");
    } catch (err) {
      setError(err.message || "Код не подошёл");
    } finally {
      setBusy(false);
    }
  };

  if (!status) return null;

  return (
    <Card pad style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <span className="gd-badge">{status.enabled ? <ShieldCheck size={19} /> : <ShieldOff size={19} />}</span>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
            Вход в панель
            {status.enabled ? (
              <Chip color="var(--gd-pos)">2FA включена</Chip>
            ) : (
              <Chip color="var(--gd-warn)">только пароль</Chip>
            )}
          </div>
          <div style={{ fontSize: 13.5, color: "var(--gd-dim)", lineHeight: 1.55, marginTop: 4 }}>
            {status.enabled
              ? `Второй фактор подключён ${status.enabledAt ? dateTime(status.enabledAt) : ""}. Без кода из приложения пароль не пускает.`
              : "Панель доступна из интернета, и пароль — единственная преграда. Подключите приложение-аутентификатор: код меняется каждые 30 секунд."}
          </div>

          {mode === "enabling" && setup && (
            <div style={{ marginTop: 14, display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-start" }}>
              <div style={{ background: "#fff", padding: 10, borderRadius: 12, width: 168, height: 168 }}>
                <QrCode value={setup.otpauthUrl} />
              </div>
              <div style={{ flex: 1, minWidth: 220, fontSize: 13.5, lineHeight: 1.55 }}>
                <div>1. Откройте Google Authenticator, Aegis или 1Password и отсканируйте QR.</div>
                <div style={{ marginTop: 4 }}>
                  Или введите секрет вручную:{" "}
                  <code className="gd-mono" style={{ userSelect: "all" }}>{setup.secret}</code>
                </div>
                <div style={{ marginTop: 4 }}>2. Введите код из приложения — только после этого фактор включится.</div>
              </div>
            </div>
          )}

          {mode !== "idle" && (
            <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                className="gd-input"
                style={{ width: 140, letterSpacing: 3, fontVariantNumeric: "tabular-nums" }}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="000000"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                onKeyDown={(e) => e.key === "Enter" && code.length === 6 && confirm()}
                autoFocus
              />
              <Button variant={mode === "enabling" ? "primary" : "danger"} disabled={busy || code.length !== 6} onClick={confirm}>
                {mode === "enabling" ? "Включить" : "Выключить"}
              </Button>
              <Button
                disabled={busy}
                onClick={() => {
                  setMode("idle");
                  setSetup(null);
                  setCode("");
                  setError("");
                }}
              >
                Отмена
              </Button>
            </div>
          )}
          {error && <div style={{ marginTop: 8, fontSize: 13, color: "var(--gd-neg)" }}>{error}</div>}
        </div>

        {mode === "idle" && (
          <div>
            {status.enabled ? (
              <Button size="sm" disabled={busy} onClick={() => setMode("disabling")}>
                <KeyRound size={14} /> Выключить
              </Button>
            ) : (
              <Button variant="primary" size="sm" disabled={busy} onClick={begin}>
                <KeyRound size={14} /> Включить 2FA
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
