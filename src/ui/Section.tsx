import type { ReactNode } from 'react';
import { cn } from './cn';

/** Sahifa ichidagi nomlangan blok (karta ramkasiz): sarlavha + izoh + o'ngda harakatlar. */
export function Section({
  title,
  description,
  actions,
  children,
  className,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={cn('min-w-0', className)} aria-labelledby={id ? `${id}-title` : undefined} id={id}>
      {/* Bo'lim nomi — bosh harfli mikro-yorliq va ostida ingichka chiziq:
          sahifa bo'limlarga bo'lingani ko'rinadi, ajratish uchun oraliq
          emas, chiziq ishlatiladi. */}
      <div className="mb-2.5 flex flex-wrap items-end justify-between gap-x-3 gap-y-1.5 border-b border-border pb-1.5">
        <div className="min-w-0">
          <h2 id={id ? `${id}-title` : undefined} className="intel-micro intel-micro-wrap !text-fg">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-[12px] leading-4 text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-1.5">{actions}</div>}
      </div>
      {children}
    </section>
  );
}
