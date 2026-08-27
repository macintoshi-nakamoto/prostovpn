import { useEffect, useRef, useState } from "react";

/*
  Анимированные эмодзи из нашего телеграм-пака ProstoVPNcc.

  Исходник — .tgs (гзипованный Lottie), распакованный в JSON при выкладке
  (public/assets/tma/*.json). Плеер грузится лениво отдельным чанком, чтобы
  не тяжелить главный бандл; пока анимация не готова — статичный кадр .webp,
  он же остаётся навсегда, если что-то не загрузилось.
*/
export function TgsEmoji({ name, size = 64, alt = "" }) {
  const box = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let anim;
    let alive = true;
    (async () => {
      try {
        const [{ default: lottie }, data] = await Promise.all([
          import("lottie-web/build/player/lottie_light"),
          fetch(`/assets/tma/${name}.json`).then((r) => r.json()),
        ]);
        if (!alive || !box.current) return;
        anim = lottie.loadAnimation({
          container: box.current,
          renderer: "svg",
          loop: true,
          autoplay: true,
          animationData: data,
        });
        setReady(true);
      } catch {
        // остаёмся на статичном кадре
      }
    })();
    return () => {
      alive = false;
      anim?.destroy();
    };
  }, [name]);

  return (
    <span
      className="tgs"
      style={{ width: size, height: size }}
      aria-hidden={alt ? undefined : "true"}
    >
      {!ready && <img src={`/assets/tma/${name}.webp`} alt={alt} width={size} height={size} />}
      <span ref={box} className="tgs-box" style={ready ? undefined : { display: "none" }} />
    </span>
  );
}
