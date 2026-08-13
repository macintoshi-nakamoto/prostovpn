import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session.jsx";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { HeroOrbit } from "../components/HeroOrbit.jsx";
import { ApiError, getToken } from "../lib/api";
import { useT } from "../lib/i18n/index.jsx";
import "./login.css";

/**
 * Вход и регистрация — цельный оранжевый экран, как в макете.
 *
 * Формы в белой карточке больше нет: поля лежат прямо на фирменном фоне
 * белыми плашками, справа парит ключ. Экран читается как продолжение героя
 * на главной, а не как отдельная страница чужого вида.
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
  const [showPass, setShowPass] = useState(false);
  // Со снятой галкой токен живёт до закрытия вкладки — это про чужой
  // компьютер. По умолчанию включена: свой браузер у большинства.
  const [remember, setRemember] = useState(true);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  /*
  Метка на <html> на время этого экрана.

  Оттянутая страница показывает не её фон, а холст под ней — а он белый по
  теме, и на оранжевом экране это выглядит дырой. Красить холст глобально
  нельзя: на остальных страницах он верный. Стили метки — в login.css.
  */
  useEffect(() => {
    document.documentElement.classList.add("lg-page");
    return () => document.documentElement.classList.remove("lg-page");
  }, []);

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
      if (isLogin) await signIn(login.trim(), password, remember);
      else await signUp(login.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  };

  return (
    <>
      {/* Шапка та же, что на лендинге, и в том же прозрачном виде: фон под
          ней теперь такой же оранжевый, как герой на главной. */}
      <SiteHeader />
      <main className="lg">
        <div className="lg-glow" aria-hidden="true" />
        {/* Те же размытые объекты, что на главной, — они держат глубину за
            формой и подхватывают движение ключа. */}
        <img className="lg-far lg-far-arc" src="/assets/ic-arc.webp" alt="" aria-hidden="true" />
        <img
          className="lg-far lg-far-devices"
          src="/assets/ic-devices.webp"
          alt=""
          aria-hidden="true"
        />

        <div className="wrap lg-in">
          <div className="lg-form">
            <h1 className="lg-title">{isLogin ? t("login.title") : t("login.titleSignup")}</h1>
            <p className="lg-sub">{isLogin ? t("login.subSignin") : t("login.subSignup")}</p>

            <form onSubmit={submit} noValidate>
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
                    placeholder={
                      isLogin ? t("login.placeholderPassword") : t("login.placeholderNewPassword")
                    }
                    autoComplete={isLogin ? "current-password" : "new-password"}
                  />
                  <button type="button" onClick={() => setShowPass((v) => !v)}>
                    {showPass ? t("login.hide") : t("login.show")}
                  </button>
                </div>
              </label>

              {/* Почту здесь не спрашиваем: она нужна только для чеков, и
                  добавить её можно в кабинете — на входе это лишнее поле
                  между человеком и его аккаунтом. */}
              {!isLogin && (
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
              )}

              {isLogin && (
                <div className="lg-row">
                  <label className="lg-remember">
                    <input
                      type="checkbox"
                      checked={remember}
                      onChange={(e) => setRemember(e.target.checked)}
                    />
                    <span>{t("login.remember")}</span>
                  </label>
                  {/* Восстановления пароля у нас нет — его возвращает
                      поддержка, поэтому ссылка ведёт к ней, а не в мёртвый
                      якорь. */}
                  <Link to="/contacts" className="lg-forgot">
                    {t("login.forgot")}
                  </Link>
                </div>
              )}

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

              {error && (
                <div className="lg-error" role="alert">
                  {error}
                </div>
              )}

              <div className="lg-actions">
                <button type="submit" className="lg-submit" disabled={busy}>
                  {busy
                    ? isLogin
                      ? t("login.busySignin")
                      : t("login.busySignup")
                    : isLogin
                      ? t("login.submitSignin")
                      : t("login.submitSignup")}
                </button>
                <button
                  type="button"
                  className="lg-switch"
                  onClick={() => switchMode(isLogin ? "register" : "login")}
                >
                  {isLogin ? t("login.submitSignup") : t("login.submitSignin")}
                </button>
              </div>
            </form>

            <p className="lg-help">
              {t("login.help")} <Link to="/contacts">{t("login.helpLink")}</Link>
            </p>
          </div>

          {/* Кольца — из макета: две плоские орбиты, по которым ключ и
              «висит». Они постоянные, поэтому вращение очень медленное:
              заметить его можно, только задержавшись взглядом. */}
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
