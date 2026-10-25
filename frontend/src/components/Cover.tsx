import { useState } from 'react';
import { classNames } from '../lib';

export function Cover({
  title,
  localUrl,
  remoteUrl,
  className,
}: {
  title: string;
  localUrl?: string | null;
  remoteUrl?: string | null;
  className?: string;
}) {
  const sources = [localUrl, remoteUrl].filter((value): value is string => Boolean(value));
  const sourceKey = sources.join('|');
  const [failures, setFailures] = useState<{ key: string; failed: Set<string> }>(() => ({
    key: sourceKey,
    failed: new Set(),
  }));
  const failed = failures.key === sourceKey ? failures.failed : new Set<string>();
  const src = sources.find((source) => !failed.has(source));

  return (
    <div className={classNames('cover', !src && 'cover-empty', className)}>
      {src ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => {
            setFailures((current) => ({
              key: sourceKey,
              failed: new Set([
                ...(current.key === sourceKey ? current.failed : []),
                src,
              ]),
            }));
          }}
        />
      ) : (
        <div className="cover-fallback" aria-hidden="true">
          <span className="cover-rune">ᛗ</span>
          <span className="cover-initial">{title.trim().charAt(0).toUpperCase() || '·'}</span>
        </div>
      )}
      <span className="cover-sheen" aria-hidden="true" />
    </div>
  );
}
