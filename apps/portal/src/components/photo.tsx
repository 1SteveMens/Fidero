'use client';
/* A photo that never shows a broken-image icon: when there is no picture, or it
 * fails to load, a neutral block with a small house mark takes its place. */
import React, { useState } from 'react';

type Props = {
  src?: string | null;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
  loading?: 'lazy' | 'eager';
};

export function Photo({ src, alt, className, style, loading }: Props) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className={`photo-missing ${className ?? ''}`} style={style} role="img" aria-label={`${alt}: no photo available`}>
        <svg width="36" height="36" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
          <path d="M3 11.5 12 4l9 7.5" />
          <path d="M5.5 10v9.5h13V10" />
          <path d="M10 19.5v-5h4v5" />
        </svg>
        <span>No photo</span>
      </div>
    );
  }
  // A picture rendered on the server can fail before React listens for errors: check once on mount.
  const check = (el: HTMLImageElement | null) => { if (el && el.complete && el.naturalWidth === 0) setFailed(true); };
  // eslint-disable-next-line @next/next/no-img-element
  return <img ref={check} src={src} alt={alt} className={className} style={style} loading={loading} onError={() => setFailed(true)} />;
}
