import { useReveal, useParallax } from "../lib/hooks";

/**
 * Появление при прокрутке.
 *
 * Вариант задаёт характер движения, а не только «выплыть снизу»:
 *
 *   up    — обычный блок текста, всплывает снизу;
 *   zoom  — заголовок секции: чуть приближается и проявляется;
 *   art   — картинка: выходит из размытия с поворотом и увеличением, то
 *           есть заметно, — на объектах это и просили;
 *   left/right — карточки и списки, приезжают со своей стороны.
 *
 * delay сдвигает старт, чтобы соседние элементы всплывали каскадом.
 */
export function Reveal({
  children,
  delay = 0,
  variant = "up",
  as: Tag = "div",
  className,
  style,
  ...rest
}) {
  const ref = useReveal();
  return (
    <Tag
      ref={ref}
      data-reveal={variant}
      className={className}
      style={{ "--reveal-delay": delay ? `${delay}ms` : undefined, ...style }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * Картинка, которая держит на себе внимание.
 *
 * Три эффекта разом и намеренно: эффектный выход из размытия при появлении,
 * медленный параллакс при прокрутке (объект живёт отдельно от страницы) и
 * бесконечное покачивание. Обёртка нужна, потому что transform у параллакса
 * и у анимации появления — одно и то же свойство: на внешнем элементе едет
 * параллакс, на внутреннем происходит появление, и они не спорят.
 */
export function ArtImage({
  src,
  alt = "",
  className,
  delay = 0,
  speed = 0.12,
  rotate = 0,
  float = true,
  ...rest
}) {
  const parallax = useParallax(speed, { rotate });
  const reveal = useReveal({ threshold: 0.05 });

  /*
  Три слоя, потому что три движения используют одно и то же свойство
  transform: параллакс на внешнем, бесконечное покачивание на среднем,
  появление на самой картинке. На одном элементе последнее объявленное
  затирало бы остальные.
  */
  const webp = src.replace(/\.png$/i, ".webp");

  return (
    <span ref={parallax} className={`art${className ? ` ${className}` : ""}`}>
      <span className={float ? "art-float" : "art-still"}>
        <picture>
          {webp !== src && <source srcSet={webp} type="image/webp" />}
          <img
            ref={reveal}
            data-reveal="art"
            src={src}
            alt={alt}
            className="art-img"
            style={{ "--reveal-delay": delay ? `${delay}ms` : undefined }}
            loading="lazy"
            {...rest}
          />
        </picture>
      </span>
    </span>
  );
}
