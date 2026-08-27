const STRIPES = {
  de: ["h", "#000000", "#dd0000", "#ffce00"],
  nl: ["h", "#ae1c28", "#ffffff", "#21468b"],
  ru: ["h", "#ffffff", "#0039a6", "#d52b1e"],
  fr: ["v", "#002395", "#ffffff", "#ed2939"],
  it: ["v", "#008c45", "#f4f5f0", "#cd212a"],
  be: ["v", "#000000", "#fdda24", "#ef3340"],
  ie: ["v", "#169b62", "#ffffff", "#ff883e"],
  ro: ["v", "#002b7f", "#fcd116", "#ce1126"],
  at: ["h", "#ed2939", "#ffffff", "#ed2939"],
  lv: ["h", "#9e3039", "#ffffff", "#9e3039"],
  pl: ["h", "#ffffff", "#dc143c"],
  ua: ["h", "#0057b7", "#ffd700"],
  id: ["h", "#ce1126", "#ffffff"],
  ee: ["h", "#0072ce", "#000000", "#ffffff"],
  lt: ["h", "#fdb913", "#006a44", "#c1272d"],
  bg: ["h", "#ffffff", "#00966e", "#d62612"],
  hu: ["h", "#cd2a3e", "#ffffff", "#436f4d"],
  lu: ["h", "#ed2939", "#ffffff", "#00a1de"],
  es: ["h", "#aa151b", "#f1bf00", "#aa151b"],
};

export function Flag({ code, title }) {
  const key = (code || "").trim().toLowerCase();
  const stripes = STRIPES[key];

  if (!stripes) {
    return (
      <span className="sheet-flag-code" aria-hidden="true">
        {key ? key.toUpperCase().slice(0, 2) : "•"}
      </span>
    );
  }

  const [dir, ...colors] = stripes;
  const size = 100 / colors.length;
  return (
    <svg
      className="sheet-flag"
      viewBox="0 0 30 21"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label={title || ""}
      focusable="false"
    >
      {colors.map((color, i) =>
        dir === "h" ? (
          <rect key={i} x="0" y={(21 * size * i) / 100} width="30" height={(21 * size) / 100} fill={color} />
        ) : (
          <rect key={i} x={(30 * size * i) / 100} y="0" width={(30 * size) / 100} height="21" fill={color} />
        ),
      )}
    </svg>
  );
}
