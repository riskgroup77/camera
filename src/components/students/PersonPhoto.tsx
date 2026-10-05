import { useEffect, useState } from 'react';
import { cn, initials, TONE_SOFT, TONE_SOLID, type Tone } from '../../ui';

/** Katta yuz surati (profil sarlavhasi, Drawer): surat yoki bosh harflar,
 *  pastda holat rangi chizig'i. O'lcham — `className` orqali (h-/w-). */
export function PersonPhoto({
  name,
  src,
  tone,
  className,
  textClassName = 'text-3xl',
}: {
  name: string;
  src?: string | null;
  /** Holat rangi (pastki chiziq). */
  tone?: Tone | null;
  className?: string;
  textClassName?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const showImage = src && !failed;
  return (
    <div
      className={cn(
        'relative shrink-0 overflow-hidden rounded-card border border-border bg-surface-2',
        !showImage && TONE_SOFT[tone ?? 'primary'],
        className,
      )}
    >
      {showImage ? (
        <img src={src} alt={name} className="h-full w-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <span role="img" aria-label={name} className={cn('absolute inset-0 flex items-center justify-center font-semibold opacity-80', textClassName)}>
          {initials(name)}
        </span>
      )}
      {tone && <span className={cn('absolute inset-x-0 bottom-0 h-1', TONE_SOLID[tone])} aria-hidden="true" />}
    </div>
  );
}
