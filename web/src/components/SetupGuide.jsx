import { useEffect, useState } from "react";
import { GuideBody } from "./GuideBody.jsx";
import { SetupChooser } from "./SetupChooser.jsx";
import { SetupExternal } from "./SetupExternal.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./setup-guide.css";
import "./setup-paths.css";

const CHOICE_KEY = "prosto_setup_path";

/**
 * Раздел установки: сперва развилка, дальше выбранный путь.
 *
 * Выбор помним, но не запираем: у человека может смениться устройство или
 * привычка, и вернуться к развилке должно быть так же просто, как выбрать
 * впервые. Поэтому кнопка «другой способ» есть в обоих разделах.
 */
export function SetupGuide({ login }) {
  const { t } = useI18n();
  const [path, setPath] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let saved = null;
    try {
      saved = window.localStorage.getItem(CHOICE_KEY);
    } catch {
      // Приватное окно или запрет на хранилище — просто спросим заново.
    }
    if (saved === "app" || saved === "external") setPath(saved);
    setReady(true);
  }, []);

  const choose = (next) => {
    setPath(next);
    try {
      window.localStorage.setItem(CHOICE_KEY, next);
    } catch {
      // Не сохранилось — не беда, в этот раз всё равно откроется выбранное.
    }
  };

  const reset = () => {
    setPath(null);
    try {
      window.localStorage.removeItem(CHOICE_KEY);
    } catch {
      // см. выше
    }
  };

  // До чтения хранилища ничего не рисуем: иначе развилка мигнёт тем, кто
  // давно всё выбрал.
  if (!ready) return <div className="sg" />;

  if (!path) return <div className="sg"><SetupChooser onPick={choose} /></div>;

  if (path === "external") {
    return (
      <div className="sg">
        <SetupExternal onSwitch={reset} />
      </div>
    );
  }

  return (
    <div className="sg">
      <div className="sg-switchbar">
        <span className="sg-switchbar-text">{t("setup.app.hint")}</span>
        <button type="button" className="sx-switch" onClick={reset}>
          {t("setup.ext.switch")}
        </button>
      </div>
      <GuideBody login={login} embedded />
    </div>
  );
}
