import { TgsEmoji } from "./TgsEmoji.jsx";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Развилка, с которой начинается установка.
 *
 * Показывается, пока человек не выбрал путь. Выбор не окончательный —
 * переключиться можно в любой момент, поэтому здесь важно не «правильно
 * решить», а честно объяснить разницу: наше приложение переключает протокол
 * и страну само, стороннее этого не умеет, зато его можно поставить рядом с
 * тем, чем человек уже пользуется.
 */
export function TmaSetupChooser({ onPick }) {
  const { t } = useI18n();

  const cards = [
    {
      id: "app",
      emoji: "thumbup",
      badge: t("setup.pick.app.badge"),
      title: t("setup.pick.app.title"),
      lead: t("setup.pick.app.lead"),
      points: [t("setup.pick.app.p1"), t("setup.pick.app.p2"), t("setup.pick.app.p3")],
      action: t("setup.pick.app.action"),
      accent: true,
    },
    {
      id: "external",
      emoji: "goldkey",
      badge: t("setup.pick.ext.badge"),
      title: t("setup.pick.ext.title"),
      lead: t("setup.pick.ext.lead"),
      points: [t("setup.pick.ext.p1"), t("setup.pick.ext.p2"), t("setup.pick.ext.p3")],
      action: t("setup.pick.ext.action"),
      accent: false,
    },
  ];

  return (
    <div className="ap ap-setup pk">
      <div className="pk-head">
        <span className="pk-title">{t("setup.pick.title")}</span>
        <span className="pk-lead">{t("setup.pick.lead")}</span>
      </div>

      {cards.map((card) => (
        <div className={"ap-card pk-card" + (card.accent ? " pk-card-on" : "")} key={card.id}>
          <div className="ap-head">
            <span className="ap-ic ap-ic-emoji">
              <TgsEmoji name={card.emoji} size={54} />
            </span>
            <span className="ap-head-body">
              <span className="pk-badge">{card.badge}</span>
              <span className="ap-title">{card.title}</span>
              <span className="ap-sub">{card.lead}</span>
            </span>
          </div>

          <ul className="pk-points">
            {card.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>

          <button
            type="button"
            className={"pk-btn" + (card.accent ? " pk-btn-on" : "")}
            onClick={() => onPick(card.id)}
          >
            {card.action}
          </button>
        </div>
      ))}

      <p className="pk-foot">{t("setup.pick.foot")}</p>
    </div>
  );
}
