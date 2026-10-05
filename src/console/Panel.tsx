import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'motion/react';
import { Maximize2, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../ui';
import { EASE, scrim, spring } from './motion';

/**
 * Konsol paneli.
 *
 * Yoyilgan ko'rinish hujjat ILDIZIGA chiqariladi (portal): aks holda u
 * `main` ning z-qatlami ichida qolib, yuqoridagi boshqaruv satri ostiga
 * tushib ketardi. `LayoutGroup` (ConsoleShell) ikki nusxani bog'lab
 * turadi, shuning uchun siljish animatsiyasi buzilmaydi.
 *
 * Har panel setkada o'z joyini egallaydi va bosilganda BUTUN maydonga
 * yoyiladi — yangi sahifaga o'tilmaydi, shuning uchun kontekst
 * yo'qolmaydi va sahifa siljishi (scroll) ham kerak emas: joy yetmasa
 * panel kattalashadi.
 *
 * Yoyilish `layoutId` orqali: bitta element ikki holat orasida
 * siljiydi, ikkita alohida oyna emas.
 */

export interface PanelProps {
  id: string;
  title: string;
  /** O'ng yuqoridagi qisqa qiymat (son, holat). */
  badge?: ReactNode;
  /** Jonli manba — sarlavhada nuqta bilan belgilanadi. */
  live?: boolean;
  /** Setkadagi joyi: Tailwind `col-span-*` / `row-span-*`. */
  area?: string;
  expanded: boolean;
  onExpand: (id: string | null) => void;
  /** Yoyilganda ko'rsatiladigan boshqacha (kengaytirilgan) mazmun. */
  full?: ReactNode;
  /** Panelning istalgan joyini bosish uni kattalashtirsinmi. Ichida filtr va
   *  tugmalar bor panelda false — aks holda filtrni bosish panelni ochib yuboradi;
   *  kattalashtirish faqat burchakdagi tugma bilan. */
  clickToExpand?: boolean;
  children: ReactNode;
}

export default function Panel({
  id,
  title,
  badge,
  live = false,
  area,
  expanded,
  onExpand,
  full,
  clickToExpand = true,
  children,
}: PanelProps) {
  // Yoyilganda setkadagi nusxa KO'RINMAYDI (opacity-0), lekin baribir
  // chiziladi — shuning uchun unga OG'IR mazmun (yoyilgan ko'rinish)
  // berilmaydi: aks holda ichkaridagi sahifa ikki marta yuklanib, ikki
  // marta so'rov yuborardi.
  const body = (content: ReactNode) => (
    <>
      <header className="flex shrink-0 items-center gap-2 px-4 py-3">
        <h2 className="flex items-center gap-1.5 text-[14px] font-bold tracking-[-0.02em] text-fg">
          {/* Jonli manba — kichik nuqta. Ilgari panel ustidan pastga
              yuguradigan ko'k chiziq bor edi: u ko'zni charchatardi. */}
          {live && <span aria-hidden="true" className="live-dot h-1.5 w-1.5 shrink-0 rounded-full bg-success" />}
          {title}
        </h2>
        <span className="ms-auto flex items-center gap-2">
          {badge}
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onExpand(expanded ? null : id);
            }}
            aria-label={expanded ? `${title} — yopish` : `${title} — kattalashtirish`}
            className="grid h-7 w-7 place-items-center rounded-full bg-surface-2 text-subtle transition-colors hover:bg-primary-soft hover:text-primary"
          >
            {expanded ? <X size={14} aria-hidden="true" /> : <Maximize2 size={13} aria-hidden="true" />}
          </button>
        </span>
      </header>
      <div className="relative min-h-0 flex-1 overflow-hidden">{content}</div>
    </>
  );

  return (
    <>
      <motion.section
        layoutId={`panel-${id}`}
        transition={spring}
        aria-label={title}
        onClick={clickToExpand ? () => !expanded && onExpand(id) : undefined}
        className={cn(
          'panel-enter glass relative flex min-h-0 min-w-0 flex-col overflow-hidden',
          clickToExpand && 'glass-hover',
          clickToExpand && !expanded && 'cursor-pointer',
          expanded && 'pointer-events-none opacity-0',
          area,
        )}
      >
        {body(children)}
      </motion.section>

      {createPortal(
        <AnimatePresence>
        {expanded && (
          <>
            <motion.div
              variants={scrim}
              initial="hidden"
              animate="show"
              exit="exit"
              onClick={() => onExpand(null)}
              className="fixed inset-0 z-40 bg-slate-900/20 backdrop-blur-[2px]"
            />
            <motion.section
              layoutId={`panel-${id}`}
              transition={spring}
              aria-label={title}
              className={cn(
                'glass fixed inset-3 z-50 flex min-h-0 flex-col overflow-hidden sm:inset-6',
                    )}
            >
              {body(full ?? children)}
            </motion.section>
          </>
        )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}

/** Panel ichidagi katta raqam — konsolning asosiy "ovozi". */
export function BigNumber({
  value,
  unit,
  tone,
  sub,
}: {
  value: ReactNode;
  unit?: string;
  tone?: string;
  sub?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col justify-center gap-1 px-3 py-2">
      <motion.span
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: EASE }}
        className={cn('text-display text-[clamp(28px,4.2vh,52px)] font-bold leading-none', tone)}
      >
        {value}
        {unit && <span className="ms-1 text-[0.4em] font-medium text-muted">{unit}</span>}
      </motion.span>
      {sub && <span className="truncate text-[11px] text-muted">{sub}</span>}
    </div>
  );
}
