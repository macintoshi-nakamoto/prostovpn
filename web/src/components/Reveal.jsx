import { useReveal, useParallax } from "../lib/hooks";

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
