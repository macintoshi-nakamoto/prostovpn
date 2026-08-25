import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { HeroOrbit } from "../components/HeroOrbit.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./login.css";

export function Reset() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const token = params.get("token") || "";

  useEffect(() => {
    document.documentElement.classList.add("lg-page");
    return () => document.documentElement.classList.remove("lg-page");
  }, []);

  return (
    <>
      <SiteHeader />
      <main className="lg">
        <div className="lg-glow" aria-hidden="true" />
        <img className="lg-far lg-far-arc" src="/assets/ic-arc.webp" alt="" aria-hidden="true" />
        <img
          className="lg-far lg-far-devices"
          src="/assets/ic-devices.webp"
          alt=""
          aria-hidden="true"
        />
        <div className="wrap lg-in">
          <div className="lg-form">
            {token ? <SetPassword token={token} /> : <AskEmail />}
            <p className="lg-help">
              {t("login.help")} <Link to="/contacts">{t("login.helpLink")}</Link>
            </p>
          </div>
          <div className="lg-key">
            <span className="lg-ring lg-ring-1" aria-hidden="true" />
            <span className="lg-ring lg-ring-2" aria-hidden="true" />
            <HeroOrbit src="/assets/obj-key.png" />
          </div>
        </div>
      </main>
    </>
  );
}

function AskEmail() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? t("reset.tooMany")
          : t("reset.failed"),
      );
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <>
        <h1 className="lg-title">{t("reset.sentTitle")}</h1>
        <p className="lg-sub">{t("reset.sentText")}</p>
        <Link className="lg-submit lg-submit-link" to="/login">
          {t("reset.backToLogin")}
        </Link>
      </>
    );
  }

  return (
    <>
      <h1 className="lg-title">{t("reset.askTitle")}</h1>
      <p className="lg-sub">{t("reset.askText")}</p>
      <form onSubmit={submit}>
        <label className="lg-field">
          <input
            type="email"
            required
            autoFocus
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={busy}
          />
        </label>
        {error && (
          <div className="lg-error" role="alert">
            {error}
          </div>
        )}
        <button className="lg-submit" type="submit" disabled={busy}>
          {busy ? t("reset.sending") : t("reset.send")}
        </button>
      </form>
      <p className="lg-help">
        <Link to="/login">{t("reset.backToLogin")}</Link>
      </p>
    </>
  );
}

function SetPassword({ token }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [state, setState] = useState({ checking: true, valid: false, login: null });
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const check = useCallback(async () => {
    try {
      const result = await api.checkResetToken(token);
      setState({ checking: false, valid: Boolean(result?.valid), login: result?.login || null });
    } catch {
      setState({ checking: false, valid: false, login: null });
    }
  }, [token]);

  useEffect(() => {
    check();
  }, [check]);

  const submit = async (event) => {
    event.preventDefault();
    if (password !== repeat) {
      setError(t("reset.mismatch"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("reset.failed"));
      setBusy(false);
    }
  };

  if (state.checking) {
    return <p className="lg-sub">{t("reset.checking")}</p>;
  }

  if (!state.valid) {
    return (
      <>
        <h1 className="lg-title">{t("reset.deadTitle")}</h1>
        <p className="lg-sub">{t("reset.deadText")}</p>
        <Link className="lg-submit lg-submit-link" to="/reset">
          {t("reset.askAgain")}
        </Link>
      </>
    );
  }

  if (done) {
    return (
      <>
        <h1 className="lg-title">{t("reset.doneTitle")}</h1>
        <p className="lg-sub">{t("reset.doneText")}</p>
        <button className="lg-submit" onClick={() => navigate("/login")}>
          {t("reset.goLogin")}
        </button>
      </>
    );
  }

  return (
    <>
      <h1 className="lg-title">{t("reset.setTitle")}</h1>
      <p className="lg-sub">{t("reset.setText", { login: state.login })}</p>
      <form onSubmit={submit}>
        <label className="lg-field">
          <input
            type="password"
            required
            minLength={8}
            autoFocus
            placeholder={t("reset.newPassword")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
          />
        </label>
        <label className="lg-field">
          <input
            type="password"
            required
            minLength={8}
            placeholder={t("reset.repeatPassword")}
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            disabled={busy}
          />
        </label>
        {error && (
          <div className="lg-error" role="alert">
            {error}
          </div>
        )}
        <button className="lg-submit" type="submit" disabled={busy}>
          {busy ? t("reset.saving") : t("reset.save")}
        </button>
      </form>
    </>
  );
}
