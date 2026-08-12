import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { Picture } from "../components/Picture.jsx";
import { ApiError } from "../lib/api";
import "./login.css";

/**
 * Вход и регистрация в одной карточке, как в макете.
 *
 * Регистрация настоящая: бэкенд заводит учётку на пробном тарифе и сразу
 * возвращает токен, поэтому после неё — прямиком в кабинет, без второго
 * ввода тех же логина и пароля.
 */
export function Login() {
  const { signIn, signUp } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/account";

  const [mode, setMode] = useState("login");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [email, setEmail] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";

  const switchMode = (next) => {
    setMode(next);
    setError("");
  };

  const messageFor = (err) => {
    if (err instanceof ApiError) {
      if (err.code === "login_taken") return "Логин занят — придумайте другой";
      if (err.code === "login_invalid")
        return "В логине только латиница, цифры, дефис, точка и подчёркивание";
      if (err.code === "bad_credentials") return "Неверный логин или пароль";
      if (err.code === "throttled") return "Слишком много попыток. Попробуйте позже";
      if (err.code === "signup_closed") return "Регистрация сейчас закрыта";
      return err.message;
    }
    return "Что-то пошло не так. Попробуйте ещё раз";
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;

    if (!login.trim() || !password) {
      setError("Заполните логин и пароль");
      return;
    }
    if (!isLogin) {
      if (password.length < 8) {
        setError("Пароль должен быть не короче 8 символов");
        return;
      }
      if (password !== password2) {
        setError("Пароли не совпадают");
        return;
      }
      if (!accepted) {
        setError("Нужно принять условия");
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
            Личный
            <br />
            кабинет
          </h1>
          <p>
            Подписка, устройства и данные для входа в одном месте. Вход только по логину и
            паролю, без привязки телефона.
          </p>
          <ul className="lg-side-list">
            <li>Статус подписки и продление</li>
            <li>До пяти устройств на аккаунт</li>
            <li>Инструкции для всех платформ</li>
          </ul>
        </div>
        <div className="lg-side-help">
          Нужна помощь? <Link to="/contacts">поддержка</Link>
        </div>
      </aside>

      <div className="lg-panel">
        <form className="lg-card" onSubmit={submit}>
          <div className="lg-tabs">
            <button
              type="button"
              className={isLogin ? "active" : ""}
              onClick={() => switchMode("login")}
            >
              Вход
            </button>
            <button
              type="button"
              className={!isLogin ? "active" : ""}
              onClick={() => switchMode("register")}
            >
              Регистрация
            </button>
          </div>

          <div className="lg-head">
            <h2>{isLogin ? "С возвращением" : "Создать аккаунт"}</h2>
            <p>
              {isLogin
                ? "Введите логин и пароль от аккаунта Prosto VPN"
                : "Логин и пароль — всё, что нужно. Почту можно добавить позже"}
            </p>
          </div>

          <div className="lg-fields">
            <label className="lg-field">
              <span>Логин</span>
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
              <span>Пароль</span>
              <div className="lg-pass">
                <input
                  type={showPass ? "text" : "password"}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError("");
                  }}
                  placeholder={isLogin ? "Ваш пароль" : "Минимум 8 символов"}
                  autoComplete={isLogin ? "current-password" : "new-password"}
                />
                <button type="button" onClick={() => setShowPass((v) => !v)}>
                  {showPass ? "Скрыть" : "Показать"}
                </button>
              </div>
            </label>

            {!isLogin && (
              <>
                <label className="lg-field">
                  <span>Повторите пароль</span>
                  <input
                    type={showPass ? "text" : "password"}
                    value={password2}
                    onChange={(e) => {
                      setPassword2(e.target.value);
                      setError("");
                    }}
                    placeholder="Ещё раз тот же пароль"
                    autoComplete="new-password"
                  />
                </label>
                <label className="lg-field">
                  <span>Почта для чеков · необязательно</span>
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
                Принимаю <Link to="/terms">условия подписки</Link> и{" "}
                <Link to="/privacy">политику обработки данных</Link>
              </span>
            </label>
          )}

          {error && <div className="lg-error">{error}</div>}

          <button type="submit" className="btn btn-primary btn-block lg-submit" disabled={busy}>
            {busy
              ? isLogin
                ? "Входим…"
                : "Создаём…"
              : isLogin
                ? "Войти"
                : "Зарегистрироваться"}
          </button>

          <div className="lg-switch">
            {isLogin ? "Ещё нет аккаунта? " : "Уже есть аккаунт? "}
            <button type="button" onClick={() => switchMode(isLogin ? "register" : "login")}>
              {isLogin ? "Зарегистрироваться" : "Войти"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
