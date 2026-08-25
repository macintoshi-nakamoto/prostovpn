import { useEffect, useState } from "react";
import { Picture } from "./Picture.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./guide-tip.css";

const SEEN_KEY = "prosto_guide_tip_appstore";

export function GuideTip({ onOpen }) {
  const { t } = useI18n();
  const [hidden, setHidden] = useState(true);

  const [headerH, setHeaderH] = useState(0);

  useEffect(() => {
    let seen = false;
    try {
      seen = localStorage.getItem(SEEN_KEY) === "1";
    } catch {}
    if (seen) return;

    const header = document.querySelector(".sh");
    if (header) setHeaderH(header.offsetHeight);

    const timer = setTimeout(() => setHidden(false), 900);
    return () => clearTimeout(timer);
  }, []);

  function close() {
    setHidden(true);
    try {
      localStorage.setItem(SEEN_KEY, "1");
    } catch {}
  }

  if (hidden) return null;

  return (
    <aside className="gd-tip" role="status" style={{ "--gd-tip-header": `${headerH}px` }}>
      <Picture
        className="gd-tip-mark"
        src="/assets/guide/tip-iphone.png"
        alt=""
        width="132"
        height="146"
        loading="eager"
        decoding="async"
      />

      <span className="gd-tip-body">
        <span className="gd-tip-title">{t("guide.tip.title")}</span>
        <span className="gd-tip-text">{t("guide.tip.text")}</span>
      </span>

      <button
        type="button"
        className="gd-tip-go"
        onClick={() => {
          close();
          onOpen?.();
        }}
      >
        {t("guide.tip.action")}
      </button>

      <button type="button" className="gd-tip-x" onClick={close} aria-label={t("guide.tip.close")}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
        </svg>
      </button>
    </aside>
  );
}
