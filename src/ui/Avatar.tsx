import { useEffect, useState } from 'react';
import { cn } from './cn';
import { TONE_RING, type Tone } from './tones';
import { initials } from './text';

export type AvatarSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

const SIZE: Record<AvatarSize, { box: string; text: string }> = {
  xs: { box: 'h-6 w-6', text: 'text-[10px]' },
  sm: { box: 'h-8 w-8', text: 'text-xs' },
  md: { box: 'h-10 w-10', text: 'text-sm' },
  lg: { box: 'h-14 w-14', text: 'text-lg' },
  xl: { box: 'h-20 w-20', text: 'text-2xl' },
};

// Ismdan barqaror rang — bir odam har joyda bir xil rangda.
const PALETTE = [
  'bg-primary-soft text-primary',
  'bg-success-soft text-success',
  'bg-warning-soft text-warning',
  'bg-info-soft text-info',
  'bg-danger-soft text-danger',
  'bg-surface-3 text-fg',
];

function paletteFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

export interface AvatarProps {
  name: string;
  src?: string | null;
  size?: AvatarSize;
  shape?: 'circle' | 'square';
  /** Holat halqasi (masalan keldi = success). */
  status?: Tone | null;
  className?: string;
}

/** Surat yoki bosh harflar. Surat yuklanmasa — avtomatik bosh harflarga o'tadi. */
export function Avatar({ name, src, size = 'md', shape = 'circle', status, className }: AvatarProps) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const { box, text } = SIZE[size];
  const showImage = src && !failed;

  return (
    <span
      className={cn(
        'relative inline-flex shrink-0 select-none items-center justify-center overflow-hidden font-semibold',
        shape === 'circle' ? 'rounded-full' : 'rounded-control',
        // Bosh harflar — monoshrift indeks belgisi, ism emas.
        !showImage && 'intel-code',
        box,
        text,
        !showImage && paletteFor(name),
        status && cn('ring-2 ring-offset-1 ring-offset-surface', TONE_RING[status]),
        className,
      )}
      title={name}
    >
      {showImage ? (
        <img src={src} alt={name} loading="lazy" className="h-full w-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <span aria-label={name} role="img">
          {initials(name)}
        </span>
      )}
    </span>
  );
}
