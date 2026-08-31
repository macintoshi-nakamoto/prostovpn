const BOX = {
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": "true",
};

export function AccountIcon() {
  return (
    <svg {...BOX} className="ni-account">
      <circle className="ni-head" cx="12" cy="8" r="3.5" />
      <path className="ni-body" d="M4.5 20c0-3.6 3.4-5.5 7.5-5.5s7.5 1.9 7.5 5.5" />
    </svg>
  );
}

export function PlanIcon() {
  return (
    <svg {...BOX} className="ni-card">
      <g className="ni-card-body">
        <rect x="2.75" y="5" width="18.5" height="14" rx="3" />
        <path d="M2.75 9.75h18.5" />
        <path d="M6.5 14.5h4" />
      </g>
    </svg>
  );
}

export function SetupIcon() {
  // Молния: «подключить в один щелчок». Контур в общем стиле, при
  // активации вспыхивает заливкой — сценка в tma.css.
  return (
    <svg {...BOX} className="ni-setup">
      <path
        className="ni-bolt"
        d="M13.2 2.8 5.9 13.1h4.6L10.8 21.2 18.1 10.9h-4.6l-.3-8.1Z"
      />
    </svg>
  );
}

export function FriendsIcon() {
  return (
    <svg {...BOX} className="ni-friends">
      <g className="ni-f1">
        <circle cx="9.5" cy="8.25" r="3.25" />
        <path d="M3.5 19.5c0-3.2 2.7-5 6-5s6 1.8 6 5" />
      </g>
      <g className="ni-f2">
        <path d="M16.25 6.3a3.25 3.25 0 0 1 0 6" />
        <path d="M18 14.9c1.9.6 3.25 2.1 3.25 4.6" />
      </g>
    </svg>
  );
}

export const NAV_ICONS = {
  account: AccountIcon,
  plan: PlanIcon,
  setup: SetupIcon,
  friends: FriendsIcon,
};
