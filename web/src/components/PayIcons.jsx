const BOX = { width: 24, height: 24, viewBox: "0 0 24 24" };

export function SbpIcon({ className = "" }) {
  return <img className={className} src="/assets/pay/sbp.svg" width="24" height="24" alt="" />;
}

export function CryptoIcon({ className = "" }) {
  return <img className={className} src="/assets/pay/bitcoin.svg" width="24" height="24" alt="" />;
}

export function TonIcon({ className = "" }) {
  return (
    <svg {...BOX} className={className} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="#0098EA" />
      <path
        d="M8.2 7.4h7.6c.74 0 1.2.8.84 1.44l-3.94 7c-.3.54-1.1.54-1.4 0l-3.94-7c-.36-.64.1-1.44.84-1.44Zm3.1 1.36H8.94l2.56 4.56V8.76h-.2Zm1.4 0v4.56l2.56-4.56h-2.56Z"
        fill="#fff"
      />
    </svg>
  );
}

export function TelegramIcon({ className = "" }) {
  return (
    <svg {...BOX} className={className} fill="none" aria-hidden="true">
      <path
        d="M21.3 4.3 2.9 11.2c-1 .4-1 1.1-.2 1.3l4.7 1.5 1.8 5.4c.2.6.4.8 1 .8.5 0 .7-.2 1-.5l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.5c.3-1.2-.5-1.8-1.7-1.4zM8.6 13.6l10.2-6.4c.5-.3.9-.1.6.2l-8.7 7.9-.3 3.6z"
        fill="#229ED9"
      />
    </svg>
  );
}
