import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { X } from 'lucide-react';
import { cn, focusRing } from '../../ui';
import { splitRecipientInput, validateRecipient, type NotificationChannel } from '../../lib/notificationsApi';

/** Qabul qiluvchilar "chip"lari: Enter, vergul yoki yopishtirish bilan
 *  qo'shiladi, kanal qoidasiga ko'ra darhol tekshiriladi (SMS — telefon
 *  +998XXXXXXXXX ga keltiriladi; Telegram — chat ID yoki @kanal). */
export default function RecipientChipsInput({
  channel,
  value,
  onChange,
  onDraftChange,
  error,
}: {
  channel: NotificationChannel;
  value: string[];
  onChange: (next: string[]) => void;
  /** Hali "chip"ga aylanmagan matn — forma uni jimgina yo'qotmasligi uchun. */
  onDraftChange?: (draft: string) => void;
  error?: string;
}) {
  const [draft, setDraftText] = useState('');
  const setDraft = (next: string) => {
    setDraftText(next);
    onDraftChange?.(next);
  };
  const [draftError, setDraftError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const inputRef = useRef<HTMLInputElement>(null);

  // Kanal almashtirilganda hali chip'ga aylanmagan matn va uning xatosi
  // ESKIRADI: SMS uchun yozilgan raqam Telegram uchun ma'nosiz, eski
  // "Telefon raqami noto'g'ri" xatosi esa ekranda qolib ketardi — va
  // forma o'sha ko'rinmas qoralama tufayli saqlashga ruxsat bermasdi.
  const prevChannel = useRef(channel);
  useEffect(() => {
    if (prevChannel.current === channel) return;
    prevChannel.current = channel;
    setDraft('');
    setDraftError(null);
    setNotice(null);
  }, [channel]);

  function commit(text: string): boolean {
    const parts = splitRecipientInput(text);
    if (parts.length === 0) return true;
    const next = [...value];
    const duplicates: string[] = [];
    for (const part of parts) {
      const [clean, err] = validateRecipient(channel, part);
      if (err) {
        setDraftError(err);
        setNotice(null);
        return false;
      }
      if (!clean) continue;
      // Takroriy qiymat JIMGINA yo'qolardi: chip paydo bo'lmasdi, maydon
      // esa tozalanardi — odam "qo'shilmadi" deb qayta-qayta urinardi.
      if (next.includes(clean)) duplicates.push(clean);
      else next.push(clean);
    }
    onChange(next);
    setDraft('');
    setDraftError(null);
    setNotice(duplicates.length ? `${duplicates.join(', ')} — allaqachon qo'shilgan` : null);
    return true;
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',' || e.key === ';') {
      e.preventDefault();
      commit(draft);
    } else if (e.key === 'Backspace' && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  }

  const placeholder = channel === 'sms' ? "+998 90 123 45 67 — Enter bilan qo'shing" : 'Chat ID (123456789, -100…) yoki @kanal';
  const shownError = draftError ?? error;

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={inputId} className="text-[13px] font-medium text-fg">
        Qabul qiluvchilar
        <span className="ml-0.5 text-danger" aria-hidden="true">
          *
        </span>
      </label>
      <div
        // Maydon "qutisi" bo'sh joyiga bosilganda ham kursor kiritish
        // joyiga tushsin — chip'lar orasidagi joy ilgari o'lik edi.
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) {
            e.preventDefault();
            inputRef.current?.focus();
          }
        }}
        className={cn(
          'flex min-h-[2.25rem] cursor-text flex-wrap items-center gap-1.5 rounded-control border bg-surface px-2 py-1.5 transition-colors',
          shownError
            ? 'border-danger focus-within:ring-[3px] focus-within:ring-danger/20'
            : 'border-border hover:border-border-strong focus-within:border-primary focus-within:ring-[3px] focus-within:ring-primary/20',
        )}
      >
        {value.map((recipient) => (
          <span
            key={recipient}
            className="inline-flex items-center gap-1 rounded-full bg-primary-soft py-0.5 pl-2.5 pr-1 font-mono text-xs font-medium text-primary"
          >
            {recipient}
            <button
              type="button"
              // Tugmani bosish kiritish maydonini "blur" qilardi, blur esa
              // qoralamani chip qilib qo'shardi — ikkala `onChange` ham
              // BIR XIL eski `value` dan hisoblanib, yangi qo'shilgani
              // darhol yo'qolardi. Fokusni umuman qo'zg'atmaymiz.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onChange(value.filter((r) => r !== recipient))}
              aria-label={`${recipient} ni olib tashlash`}
              className={cn('rounded-full p-0.5 hover:bg-primary/15', focusRing)}
            >
              <X size={12} aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          id={inputId}
          ref={inputRef}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setDraftError(null);
            setNotice(null);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => draft.trim() && commit(draft)}
          onPaste={(e) => {
            const text = e.clipboardData.getData('text');
            if (/[,;\n]/.test(text)) {
              e.preventDefault();
              commit(text);
            }
          }}
          placeholder={value.length ? '' : placeholder}
          aria-invalid={shownError ? true : undefined}
          aria-describedby={hintId}
          className="min-w-[10rem] flex-1 bg-transparent px-1 py-0.5 text-sm text-fg outline-none placeholder:text-subtle"
        />
      </div>
      <p
        id={hintId}
        className={cn('text-xs', shownError ? 'font-medium text-danger' : notice ? 'font-medium text-warning' : 'text-muted')}
        role={shownError || notice ? 'alert' : undefined}
      >
        {shownError ??
          notice ??
          (channel === 'telegram'
            ? "Guruh chat ID sini bilish uchun botni guruhga qo'shib /chatid yozing."
            : 'Bir nechta raqamni vergul bilan ajratib yopishtirish mumkin.')}
      </p>
    </div>
  );
}
