import { Picture } from "./Picture.jsx";
import { TgsEmoji } from "./TgsEmoji.jsx";
import { BRAND_ID } from "../lib/brand.js";

/*
  Фирменные элементы, которые у брендов устроены по-разному:

    BrandLogo        — логотип в шапке и подвале (Prosto — картинка,
                       Rus VPN — словесный знак в две краски);
    BrandMark        — «лицо» продукта в карте подписки;
    BrandFreezeEmoji — эмодзи паузы.

  Prosto оставлен как был: анимированные эмодзи из телеграм-пака.
*/

export function BrandLogo({ caption, className }) {
  if (BRAND_ID === "rusvpn") {
    return (
      <span className={`rv-logo${className ? ` ${className}` : ""}`}>
        {caption && <span className="rv-logo-cap">{caption}</span>}
        <span className="rv-logo-word" aria-label="Rus VPN">
          <b>RUS</b> <i>VPN</i>
        </span>
      </span>
    );
  }
  return <Picture className={className} src="/assets/logo-v3.png" alt="PROSTO" />;
}

// Круглое лицо-триколор в наушниках: белая, синяя и красная полосы, закрытые
// довольные глаза, нотки. Рисуется вектором — картинка не нужна.
function RusFace({ size }) {
  return (
    <svg
      className="rv-face"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      aria-hidden="true"
    >
      <defs>
        <clipPath id="rv-face-clip">
          <circle cx="32" cy="35" r="26" />
        </clipPath>
        <linearGradient id="rv-face-cup" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3a3f52" />
          <stop offset="1" stopColor="#15181f" />
        </linearGradient>
      </defs>
      <g clipPath="url(#rv-face-clip)">
        <rect x="4" y="8" width="56" height="18" fill="#f4f6ff" />
        <rect x="4" y="26" width="56" height="18" fill="#2f5bff" />
        <rect x="4" y="44" width="56" height="18" fill="#ff3644" />
      </g>
      <path
        d="M19 31q5-5.5 10 0M35 31q5-5.5 10 0"
        fill="none"
        stroke="#111319"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M22.5 41q9.5 8 19 0"
        fill="none"
        stroke="#111319"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path
        d="M7 37v-5a25 25 0 0 1 50 0v5"
        fill="none"
        stroke="#1f2330"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <rect x="1.5" y="30" width="10" height="17" rx="4.5" fill="url(#rv-face-cup)" />
      <rect x="52.5" y="30" width="10" height="17" rx="4.5" fill="url(#rv-face-cup)" />
      <g fill="#ff3644">
        <circle cx="55" cy="11" r="2.4" />
        <rect x="56.6" y="2" width="1.8" height="9.4" rx="0.9" />
        <path d="M56.6 2h4.4l1.4 3h-4.4z" />
      </g>
      <g fill="#2f5bff">
        <circle cx="47" cy="7" r="1.7" />
        <rect x="48.1" y="1" width="1.4" height="6.3" rx="0.7" />
      </g>
    </svg>
  );
}

export function BrandMark({ size = 62 }) {
  if (BRAND_ID === "rusvpn") return <RusFace size={size} />;
  return <TgsEmoji name="fire" size={size} />;
}

export function BrandFreezeEmoji({ size = 48 }) {
  if (BRAND_ID === "rusvpn") {
    return (
      <span className="rv-zz" style={{ width: size, height: size }} aria-hidden="true">
        <span className="rv-zz-emoji">🦀</span>
        <span className="rv-zz-z">z</span>
      </span>
    );
  }
  return <TgsEmoji name="freeze-emoji" size={size} />;
}
