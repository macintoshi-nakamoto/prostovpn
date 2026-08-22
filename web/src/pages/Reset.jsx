import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { HeroOrbit } from "../components/HeroOrbit.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./login.css";

/**
 * Смена пароля по ссылке из письма.
 *
 * Один адрес на два шага: без токена — форма «куда прислать ссылку», с
 * токеном — «придумайте новый пароль». Разводить их по разным страницам
 * незачем: человек попадает сюда либо из формы входа, либо из письма, и
 * между этими двумя состояниями он не переключается вручную.
 *
 * Годность ссылки проверяем ДО того, как показать поля. Иначе человек
 * придумывает пароль, вводит дважды и только потом узнаёт, что ссылка
 * протухла полчаса назад.
 */
export function Reset() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const token = params.get("token") || "";

  /*
  Оформление один в один как на входе: та же шапка, тот же фон, та же
  карточка. Человек приходит сюда прямо из формы входа или из письма, и
  собственный вид у этой страницы означал бы «вы попали куда-то не туда» —
  ровно то, чего на странице про пароль быть не должно.
  */
  useEffect(() => {
    document.documentElement.classList.add("lg-page");
    return () => document.documentElement.classList.remove("lg-page");
  }, []);

  return (
    <>
      <SiteHeader />
      <main className="lg">
        <div className="lg-glow" aria-hidden="true" />
        {/* Тот же размытый декор, что на входе. На мобильном именно эта
            верхняя зона (order: 1, отступ под шапку) отодвигает лист формы
            от прозрачной фиксированной шапки — без неё заголовок оказывался
            под лого и переключателями и наезжал на них. */}
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
          {/* Ключ на орбите — как на входе. Держит правую колонку на десктопе
              и верхнюю зону-отступ на мобильном. */}
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

/** Шаг первый: куда прислать ссылку. */
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
      // 429 — единственная ошибка, о которой стоит говорить: всё остальное
      // сервер намеренно не различает, чтобы форма не отвечала на вопрос
      // «а есть ли у вас такой человек».
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

/** Шаг второй: новый пароль. */
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
