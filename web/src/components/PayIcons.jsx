/**
 * Значки способов оплаты.
 *
 * СБП и биткоин — файлы в `public/assets/pay/`, а не рисунок в коде. Так их
 * меняют без правки кода и без пересборки логики: положили настоящий знак
 * от платёжного сервиса под тем же именем — и он встал на место. Рисовать
 * чужие марки руками смысла нет: похоже ещё не значит правильно.
 *
 * Размер задан в разметке и в CSS одинаковым для всех трёх, поэтому знак
 * любого размера и пропорций встанет в ряд ровно.
 *
 * Telegram остаётся в коде: он белый на синей кнопке и должен наследовать
 * цвет — картинкой этого не сделать.
 */

const BOX = { width: 24, height: 24, viewBox: "0 0 24 24" };

export function SbpIcon({ className = "" }) {
  return <img className={className} src="/assets/pay/sbp.svg" width="24" height="24" alt="" />;
}

export function CryptoIcon({ className = "" }) {
  return <img className={className} src="/assets/pay/bitcoin.svg" width="24" height="24" alt="" />;
}

/** Telegram: самолётик. Белый — кнопка под ним синяя, фирменного цвета. */
export function TelegramIcon({ className = "" }) {
  return (
    <svg {...BOX} className={className} fill="none" aria-hidden="true">
      <path
        d="M21.3 4.3 2.9 11.2c-1 .4-1 1.1-.2 1.3l4.7 1.5 1.8 5.4c.2.6.4.8 1 .8.5 0 .7-.2 1-.5l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.5c.3-1.2-.5-1.8-1.7-1.4zM8.6 13.6l10.2-6.4c.5-.3.9-.1.6.2l-8.7 7.9-.3 3.6z"
        fill="currentColor"
      />
    </svg>
  );
}
