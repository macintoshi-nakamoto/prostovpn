import { useState } from "react";
import { Lock, ShieldCheck, User } from "lucide-react";
import { useSession } from "../../lib/session";
import { Button, Field } from "../../ui";
import "./login.css";

export function LoginPage() {
  const { signIn } = useSession();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(login.trim(), password);
    } catch (err) {
      setError(err.message || "Не удалось войти");
      setBusy(false);
    }
  };

  return (
    <div className="lg-root">
      <div className="lg-orb lg-orb-1" aria-hidden="true" />
      <div className="lg-orb lg-orb-2" aria-hidden="true" />

      <form className="lg-card" onSubmit={submit}>
        <div className="lg-mark">
          <ShieldCheck size={26} />
        </div>
        <div className="lg-title">Prosto VPN</div>
        <div className="lg-sub">Панель управления</div>

        <div className="lg-fields">
          <Field label="Логин">
            <div className="lg-input">
              <User size={17} />
              <input
                value={login}
                onChange={(e) => {
                  setLogin(e.target.value);
                  setError(null);
                }}
                placeholder="admin"
                autoComplete="username"
                autoFocus
              />
            </div>
          </Field>

          <Field label="Пароль">
            <div className="lg-input">
              <Lock size={17} />
              <input
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError(null);
                }}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>
          </Field>
        </div>

        {error && <div className="lg-error">{error}</div>}

        <Button
          variant="primary"
          type="submit"
          disabled={busy || !login.trim() || !password}
          style={{ width: "100%", height: 46, borderRadius: 15, fontSize: 14.5 }}
        >
          {busy ? "Входим…" : "Войти"}
        </Button>
      </form>
    </div>
  );
}
