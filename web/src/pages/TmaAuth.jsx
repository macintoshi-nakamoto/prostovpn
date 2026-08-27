import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n/index.jsx";
import { TgsEmoji } from "../components/TgsEmoji.jsx";
import { tmaHaptic, tmaOpenLink } from "../lib/telegram.js";

const OB_KEY = "prosto_onboarded";

// Эмодзи пака к слайдам онбординга: тексты лежат в i18n (login.tmaOb).
const OB_EMOJI = ["globe", "fire", "thumbup", "robot", "rabbit"];

function seenOnboarding() {
  try {
    return localStorage.getItem(OB_KEY) === "1";
  } catch {
    return true;
  }
}

// Онбординг: полноэкранные слайды с горизонтальным снапом, параллаксом
// и живыми эмодзи. Листается пальцем и кнопкой, в конце — к регистрации.
function TmaOnboarding({ onDone }) {
  const { t, raw } = useI18n();
  const trackRef = useRef(null);
  const [index, setIndex] = useState(0);
  const slides = raw("login.tmaOb") || [];
  const last = index >= slides.length - 1;

  // Параллакс: позиция каждого слайда относительно вьюпорта уходит в CSS
  // переменные --d (сдвиг) и --a (видимость) — дальше работает чистый CSS.
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return undefined;
    const update = () => {
      const width = track.clientWidth || 1;
      const kids = track.children;
      for (let i = 0; i < kids.length; i += 1) {
        const d = (kids[i].offsetLeft - track.scrollLeft) / width;
        kids[i].style.setProperty("--d", d.toFixed(4));
        kids[i].style.setProperty("--a", Math.max(0, 1 - Math.abs(d) * 1.6).toFixed(4));
      }
      const active = Math.round(track.scrollLeft / width);
      setIndex((cur) => {
        if (cur !== active) tmaHaptic("select");
        return active;
      });
    };
    update();
    track.addEventListener("scroll", update, { passive: true });
    return () => {
      track.removeEventListener("scroll", update);
    };
  }, [slides.length]);

  const goTo = (i) => {
    const track = trackRef.current;
    if (!track) return;
    track.scrollTo({ left: i * track.clientWidth, behavior: "smooth" });
  };

  const next = () => {
    tmaHaptic("light");
    if (last) onDone("register");
    else goTo(index + 1);
  };

  return (
    <div className="ob">
      <div className="ob-top">
        <img className="ob-logo" src="/assets/logo-v3.png" alt="PROSTO" />
        <button
          type="button"
          className="ob-skip"
          onClick={() => {
            tmaHaptic("light");
            onDone("login");
          }}
        >
          {t("login.tmaObSkip")}
        </button>
      </div>

      <div className="ob-track" ref={trackRef}>
        {slides.map(([title, text], i) => (
          <section className="ob-slide" key={i}>
            <span className="ob-blob ob-blob-a" aria-hidden="true" />
            <span className="ob-blob ob-blob-b" aria-hidden="true" />
            <span className="ob-ring" aria-hidden="true" />
            <div className="ob-hero">
              <TgsEmoji name={OB_EMOJI[i] || "star"} size={124} />
            </div>
            <h1>{title}</h1>
            <p>{text}</p>
          </section>
        ))}
      </div>

      <div className="ob-foot">
        <div className="ob-dots" aria-hidden="true">
          {slides.map((_, i) => (
            <button
              key={i}
              type="button"
              tabIndex={-1}
              className={`ob-dot${i === index ? " on" : ""}`}
              onClick={() => goTo(i)}
            />
          ))}
        </div>
        <button type="button" className="ap-cta ob-next" onClick={next}>
          {last ? t("login.tmaObStart") : t("login.tmaObNext")}
        </button>
        <button
          type="button"
          className={`ob-have${last ? " show" : ""}`}
          tabIndex={last ? 0 : -1}
          onClick={() => {
            tmaHaptic("light");
            onDone("login");
          }}
        >
          {t("login.tmaObHave")}
        </button>
      </div>
    </div>
  );
}

// Вход и регистрация в стиле мини-аппа. «Забыли пароль» уводит на сайт во
// внешний браузер: сброс идёт через почту, в вебвью ему делать нечего.
export function TmaAuth() {
  const { t } = useI18n();
  const { signIn, signUp } = useSession();
  const navigate = useNavigate();
  const location = useLocation();

  const [showOb, setShowOb] = useState(() => !seenOnboarding());
  const [mode, setMode] = useState(() =>
    new URLSearchParams(location.search).get("mode") === "signup" ? "register" : "login",
  );
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";

  const finishOb = useCallback((nextMode) => {
    try {
      localStorage.setItem(OB_KEY, "1");
    } catch {}
    setMode(nextMode);
    setShowOb(false);
  }, []);

  const messageFor = (err) => {
    if (err instanceof ApiError) {
      const known = {
        login_taken: "loginTaken",
        login_invalid: "loginInvalid",
        bad_credentials: "badCredentials",
        throttled: "throttled",
        signup_closed: "signupClosed",
      }[err.code];
      return known ? t(`login.errors.${known}`) : err.message;
    }
    return t("login.errors.unknown");
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!login.trim() || !password) {
      setError(t("login.errors.empty"));
      return;
    }
    if (!isLogin) {
      if (password.length < 8) {
        setError(t("login.errors.short"));
        return;
      }
      if (password !== password2) {
        setError(t("login.errors.mismatch"));
        return;
      }
      if (!accepted) {
        setError(t("login.errors.accept"));
        return;
      }
    }
    setBusy(true);
    setError("");
    tmaHaptic("light");
    try {
      if (isLogin) await signIn(login.trim(), password, true);
      else await signUp(login.trim(), password);
      tmaHaptic("medium");
      navigate("/account", { replace: true });
    } catch (err) {
      tmaHaptic("error");
      setError(messageFor(err));
      setBusy(false);
    }
  };

  if (showOb) return <TmaOnboarding onDone={finishOb} />;

  const swapMode = (next) => {
    if (next === mode) return;
    tmaHaptic("select");
    setMode(next);
    setError("");
  };

  return (
    <div className="au">
      <div className="au-hero">
        <TgsEmoji name="goldkey" size={92} />
      </div>
      <h1 className="au-title">{isLogin ? t("login.headSignin") : t("login.headSignup")}</h1>
      <p className="au-sub">{isLogin ? t("login.subSignin") : t("login.subSignup")}</p>

      <div className="au-tabs" role="tablist">
        <span className={`au-pill${isLogin ? "" : " right"}`} aria-hidden="true" />
        <button
          type="button"
          role="tab"
          aria-selected={isLogin}
          className={isLogin ? "on" : ""}
          onClick={() => swapMode("login")}
        >
          {t("login.tabSignin")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={!isLogin}
          className={isLogin ? "" : "on"}
          onClick={() => swapMode("register")}
        >
          {t("login.tabSignup")}
        </button>
      </div>

      <form className="au-form" onSubmit={submit}>
        <label className="pd-field">
          <span>{t("login.fieldLogin")}</span>
          <input
            type="text"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <label className="pd-field au-pass">
          <span>{t("login.fieldPassword")}</span>
          <input
            type={showPass ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={isLogin ? t("login.placeholderPassword") : t("login.placeholderNewPassword")}
            autoComplete={isLogin ? "current-password" : "new-password"}
          />
          <button
            type="button"
            className="au-eye"
            onClick={() => setShowPass((v) => !v)}
            aria-pressed={showPass}
          >
            {showPass ? t("login.hide") : t("login.show")}
          </button>
        </label>

        {!isLogin && (
          <label className="pd-field">
            <span>{t("login.fieldRepeat")}</span>
            <input
              type={showPass ? "text" : "password"}
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              placeholder={t("login.placeholderRepeat")}
              autoComplete="new-password"
            />
          </label>
        )}

        {!isLogin && (
          <label className="au-accept">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            <span className="au-box" aria-hidden="true" />
            <span className="au-accept-text">
              {t("login.acceptBefore")}{" "}
              <button
                type="button"
                className="au-link"
                onClick={() => tmaOpenLink(`${window.location.origin}/terms`)}
              >
                {t("login.acceptTerms")}
              </button>{" "}
              {t("login.acceptAnd")}{" "}
              <button
                type="button"
                className="au-link"
                onClick={() => tmaOpenLink(`${window.location.origin}/privacy`)}
              >
                {t("login.acceptPrivacy")}
              </button>
            </span>
          </label>
        )}

        {error && <div className="pd-error">{error}</div>}

        <button type="submit" className="ap-cta au-submit" disabled={busy}>
          {busy
            ? isLogin
              ? t("login.busySignin")
              : t("login.busySignup")
            : isLogin
              ? t("login.submitSignin")
              : t("login.submitSignup")}
        </button>

        {isLogin && (
          <button
            type="button"
            className="au-forgot"
            onClick={() => {
              tmaHaptic("light");
              tmaOpenLink(`${window.location.origin}/reset`);
            }}
          >
            {t("login.forgot")}
          </button>
        )}
      </form>
    </div>
  );
}
