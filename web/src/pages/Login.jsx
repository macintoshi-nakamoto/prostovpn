import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { Picture } from "../components/Picture.jsx";
import { Controls } from "../components/Controls.jsx";
import { ApiError, getToken } from "../lib/api";
import { useT } from "../lib/i18n/index.jsx";
import "./login.css";

/**
 * Вход и регистрация в одной карточке, как в макете.
 *
 * Регистрация настоящая: бэкенд заводит учётку на пробном тарифе и сразу
 * возвращает токен, поэтому после неё — прямиком в кабинет, без второго
 * ввода тех же логина и пароля.
 */
export function Login() {
  const t = useT();
  const { signIn, signUp, authed } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  /*
  Возвращаемся ровно туда, откуда человека сюда отправили, — вместе с
  запросом. Без search терялся выбранный тариф: с лендинга жали «Выбрать» на
  годовом, а после входа кабинет открывался на общей вкладке, и выбор
  приходилось делать заново.
  */
  const back = location.state?.from;
  const from = back ? `${back.pathname}${back.search || ""}` : "/account";

  // Кнопка пробного периода ведёт сразу на регистрацию: человеку, который
  // ещё не завёл учётку, форма входа — тупик.
  const [mode, setMode] = useState(() =>
    new URLSearchParams(location.search).get("mode") === "signup" ? "register" : "login",
  );
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [email, setEmail] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";

  /*
  Вошедшего форма не встречает — его сразу уводит в кабинет.

  Сюда ведут все кнопки сайта: «Выбрать» на тарифах, «Попробовать
  бесплатно», значки сторов. Человек с живой сессией, нажав «Выбрать»,
  попадал на форму входа и решал, что его разлогинило, — хотя сессия
  лежала рядом нетронутой.

  Рядом с флагом сессии проверяется и сам токен, и это защита от цикла.
  На протухшем токене кабинет получает 401: api.js стирает токен и кабинет
  уводит сюда, но флаг authed в контексте остаётся старым до перезагрузки.
  Редирект по одному флагу гонял бы человека /login → /account → /login
  без остановки; пустой токен разрывает круг — форма показывается.
  */
  if (authed && getToken()) return <Navigate to={from} replace />;

  const switchMode = (next) => {
    setMode(next);
    setError("");
  };

  const messageFor = (err) => {
    if (err instanceof ApiError) {
      // Коды бэкенда переводим сами; на незнакомый код остаётся его текст —
      // он приходит по-русски, но лучше настоящая причина, чем «что-то пошло
      // не так» вместо неё.
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
    try {
      if (isLogin) await signIn(login.trim(), password);
      else await signUp(login.trim(), password, email.trim());
      navigate(from, { replace: true });
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  };

  return (
    <div className="lg-root">
      <aside className="lg-side">
        <div className="lg-side-glow" aria-hidden="true" />
        <Link to="/" className="lg-side-logo">
          <Picture src="/assets/logo.png" alt="PROSTO" />
        </Link>
        <div className="lg-side-body">
          <h1>
            {t("login.sideLine1")}
            <br />
            {t("login.sideLine2")}
          </h1>
          <p>{t("login.sideLead")}</p>
          <ul className="lg-side-list">
            {["0", "1", "2"].map((i) => (
              <li key={i}>{t(`login.sideList.${i}`)}</li>
            ))}
          </ul>
        </div>
        <div className="lg-side-help">
          {t("login.help")} <Link to="/contacts">{t("login.helpLink")}</Link>
        </div>
      </aside>

      <div className="lg-panel">
        <div className="lg-controls">
          <Controls />
        </div>
        <form className="lg-card" onSubmit={submit}>
          <div className="lg-tabs">
            <button
              type="button"
              className={isLogin ? "active" : ""}
              onClick={() => switchMode("login")}
            >
              {t("login.tabSignin")}
            </button>
            <button
              type="button"
              className={!isLogin ? "active" : ""}
              onClick={() => switchMode("register")}
            >
              {t("login.tabSignup")}
            </button>
          </div>

          <div className="lg-head">
            <h2>{isLogin ? t("login.headSignin") : t("login.headSignup")}</h2>
            <p>{isLogin ? t("login.subSignin") : t("login.subSignup")}</p>
          </div>

          <div className="lg-fields">
            <label className="lg-field">
              <span>{t("login.fieldLogin")}</span>
              <input
                type="text"
                value={login}
                onChange={(e) => {
                  setLogin(e.target.value);
                  setError("");
                }}
                placeholder="prosto_user"
                autoComplete="username"
                autoFocus
              />
            </label>

            <label className="lg-field">
              <span>{t("login.fieldPassword")}</span>
              <div className="lg-pass">
                <input
                  type={showPass ? "text" : "password"}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError("");
                  }}
                  placeholder={isLogin ? t("login.placeholderPassword") : t("login.placeholderNewPassword")}
                  autoComplete={isLogin ? "current-password" : "new-password"}
                />
                <button type="button" onClick={() => setShowPass((v) => !v)}>
                  {showPass ? t("login.hide") : t("login.show")}
                </button>
              </div>
            </label>

            {!isLogin && (
              <>
                <label className="lg-field">
                  <span>{t("login.fieldRepeat")}</span>
                  <input
                    type={showPass ? "text" : "password"}
                    value={password2}
                    onChange={(e) => {
                      setPassword2(e.target.value);
                      setError("");
                    }}
                    placeholder={t("login.placeholderRepeat")}
                    autoComplete="new-password"
                  />
                </label>
                <label className="lg-field">
                  <span>{t("login.fieldEmail")}</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                  />
                </label>
              </>
            )}
          </div>

          {!isLogin && (
            <label className="lg-check">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(e) => {
                  setAccepted(e.target.checked);
                  setError("");
                }}
              />
              <span>
                {t("login.acceptBefore")} <Link to="/terms">{t("login.acceptTerms")}</Link>{" "}
                {t("login.acceptAnd")} <Link to="/privacy">{t("login.acceptPrivacy")}</Link>
              </span>
            </label>
          )}

          {error && <div className="lg-error">{error}</div>}

          <button type="submit" className="btn btn-primary btn-block lg-submit" disabled={busy}>
            {busy
              ? isLogin
                ? t("login.busySignin")
                : t("login.busySignup")
              : isLogin
                ? t("login.submitSignin")
                : t("login.submitSignup")}
          </button>

          <div className="lg-switch">
            {isLogin ? t("login.switchToSignup") : t("login.switchToSignin")}{" "}
            <button type="button" onClick={() => switchMode(isLogin ? "register" : "login")}>
              {isLogin ? t("login.submitSignup") : t("login.submitSignin")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
