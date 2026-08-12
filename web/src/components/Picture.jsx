/**
 * Картинка с webp и запасным исходником.
 *
 * Рядом с каждым png лежит webp того же имени — он в разы легче при том же
 * виде. Браузер выбирает сам: понимает webp — берёт его, не понимает —
 * скачивает png. Держать это в одном месте проще, чем расставлять <picture>
 * по всем страницам и однажды забыть.
 */
export function Picture({ src, alt = "", className, imgClassName, style, ...rest }) {
  const webp = src.replace(/\.png$/i, ".webp");
  const hasWebp = webp !== src;

  return (
    <picture className={className} style={style}>
      {hasWebp && <source srcSet={webp} type="image/webp" />}
      <img src={src} alt={alt} className={imgClassName} {...rest} />
    </picture>
  );
}
