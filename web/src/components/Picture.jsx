export function Picture({ src, alt = "", className, imgClassName, style, ...rest }) {
  const webp = src.replace(/\.(png|jpe?g)$/i, ".webp");
  const hasWebp = webp !== src;

  return (
    <picture className={className} style={style}>
      {hasWebp && <source srcSet={webp} type="image/webp" />}
      <img src={src} alt={alt} className={imgClassName} {...rest} />
    </picture>
  );
}
