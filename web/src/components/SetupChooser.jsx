import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Развилка, с которой начинается установка.
 *
 * Показывается, пока человек не выбрал путь. Выбор не окончательный —
 * переключиться можно в любой момент, поэтому здесь важно не «правильно
 * решить», а честно объяснить разницу: наше приложение умеет переключать
 * протоколы само, стороннее — нет, но его иногда просто удобнее поставить.
 */
export function SetupChooser({ onPick }) {
  const { t } = useI18n();

  const cards = [
    {
      id: "app",
      badge: t("setup.pick.app.badge"),
      title: t("setup.pick.app.title"),
      lead: t("setup.pick.app.lead"),
      points: [
        t("setup.pick.app.p1"),
        t("setup.pick.app.p2"),
        t("setup.pick.app.p3"),
      ],
      action: t("setup.pick.app.action"),
      accent: true,
    },
    {
      id: "external",
      badge: t("setup.pick.ext.badge"),
      title: t("setup.pick.ext.title"),
      lead: t("setup.pick.ext.lead"),
      points: [
        t("setup.pick.ext.p1"),
        t("setup.pick.ext.p2"),
        t("setup.pick.ext.p3"),
      ],
      action: t("setup.pick.ext.action"),
      accent: false,
    },
  ];

  return (
    <div className="sp">
      <header className="sp-head">
        <h2 className="sp-title">{t("setup.pick.title")}</h2>
        <p className="sp-lead">{t("setup.pick.lead")}</p>
      </header>

      <div className="sp-grid">
        {cards.map((card) => (
          <article key={card.id} className={"sp-card" + (card.accent ? " sp-card-accent" : "")}>
            <span className="sp-badge">{card.badge}</span>
            <h3 className="sp-card-title">{card.title}</h3>
            <p className="sp-card-lead">{card.lead}</p>

            <ul className="sp-points">
              {card.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>

            <button
              type="button"
              className={"sp-action" + (card.accent ? " sp-action-accent" : "")}
              onClick={() => onPick(card.id)}
            >
              {card.action}
            </button>
          </article>
        ))}
      </div>

      <p className="sp-foot">{t("setup.pick.foot")}</p>
    </div>
  );
}
