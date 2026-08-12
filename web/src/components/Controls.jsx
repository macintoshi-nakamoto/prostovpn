import { useI18n } from "../lib/i18n/index.jsx";
import { useTheme } from "../lib/theme.jsx";
import "./controls.css";

/*
 * Переключатели языка и темы.
 *
 * Один компонент на весь сайт: они стоят рядом в четырёх разных шапках, и
 * разъехавшиеся по виду копии заметны сразу.
 *
 * Активный язык подсвечивает не сама кнопка, а отдельная «капля» (.ctl-thumb),
 * скользящая под подписями, — переключение выглядит переездом одного предмета,
 * а не перекраской двух кнопок. Смена темы — той же природы: солнце и луна
 * лежат в кнопке стопкой и сменяются поворотом, а не подменой узла.
 *
 * Своих вариантов оформления у компонента нет. Над героем лендинга шапка
 * прозрачная, и содержимое в ней белое — но так же там ведут себя и логотип, и
 * меню, и кнопка справа: перекрашивает их сама шапка селектором `.sh .ctl`,
 * тем же приёмом, что и всё остальное внутри неё.
 */

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="4.2" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M12 2.6v2.6M12 18.8v2.6M2.6 12h2.6M18.8 12h2.6" />
        <path d="M5.4 5.4l1.8 1.8M16.8 16.8l1.8 1.8M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8" />
      </g>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      {/* Полумесяц одной фигурой: два круга с вырезом дают шов на границе. */}
      <path
        d="M20.3 14.6A8.6 8.6 0 0 1 9.4 3.7a8.7 8.7 0 1 0 10.9 10.9z"
        fill="currentColor"
      />
    </svg>
  );
}

export function Controls() {
  const { lang, setLang, t } = useI18n();
  const { dark, toggle } = useTheme();

  return (
    <div className="ctl">
      {/*
      Языки показаны оба сразу, а не текущий с переключением по клику. Кнопка
      с надписью «RU» одинаково читается и как «сейчас русский», и как
      «нажмите, чтобы стал русский»; две кнопки с каплей на активной не
      оставляют выбора для толкования.
      */}
      <div
        className={`ctl-lang${lang === "en" ? " ctl-lang-en" : ""}`}
        role="group"
        aria-label={t("controls.language")}
      >
        <span className="ctl-thumb" aria-hidden="true" />
        <button
          type="button"
          className={lang === "ru" ? "active" : ""}
          aria-pressed={lang === "ru"}
          onClick={() => setLang("ru")}
        >
          RU
        </button>
        <button
          type="button"
          className={lang === "en" ? "active" : ""}
          aria-pressed={lang === "en"}
          onClick={() => setLang("en")}
        >
          EN
        </button>
      </div>

      <button
        type="button"
        className={`ctl-theme${dark ? " ctl-theme-dark" : ""}`}
        onClick={toggle}
        // Подпись называет то, что произойдёт по нажатию, а не текущее
        // состояние: иконка и так показывает, куда переключаемся.
        title={dark ? t("controls.themeToLight") : t("controls.themeToDark")}
        aria-label={dark ? t("controls.themeToLight") : t("controls.themeToDark")}
      >
        <span className="ctl-ic ctl-ic-sun">
          <SunIcon />
        </span>
        <span className="ctl-ic ctl-ic-moon">
          <MoonIcon />
        </span>
      </button>
    </div>
  );
}
