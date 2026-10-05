import { useEffect, useRef, useState } from 'react';
import { Check, Copy, ExternalLink } from 'lucide-react';
import { Button, buttonClasses, controlBase } from '../../ui';
import type { TelegramLink } from '../../lib/notificationsApi';

/** Bir martalik bog'lash havolasi: ochish yoki nusxalab yuborish.
 *  Havola botga "/start <kod>" yuboradi — kod ishlatilgach yaroqsiz bo'ladi. */
export default function TelegramLinkBox({ link, hint }: { link: TelegramLink; hint?: string }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  // Taymer komponent yopilganda bekor qilinadi — aks holda oyna 2 soniya
  // ichida yopilsa, mavjud bo'lmagan komponentga setState yuborilardi.
  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  async function copy() {
    window.clearTimeout(timerRef.current);
    try {
      await navigator.clipboard.writeText(link.deepLink);
      setCopied(true);
      setCopyFailed(false);
      timerRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard ruxsati yo'q (http, eski brauzer). Ilgari xato JIMGINA
      // yutilardi: tugma hech narsa qilmagandek tuyulardi. Endi nima
      // qilish kerakligi aytiladi.
      setCopied(false);
      setCopyFailed(true);
      inputRef.current?.select();
      timerRef.current = window.setTimeout(() => setCopyFailed(false), 5000);
    }
  }

  return (
    <div className="border border-info/30 bg-info-soft px-3 py-2.5">
      <p className="mb-2 text-[13px] leading-5 text-fg">{hint ?? "Havolani oching va Telegram'da «Start» tugmasini bosing."}</p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={inputRef}
          readOnly
          value={link.deepLink}
          onFocus={(e) => e.currentTarget.select()}
          aria-label="Bog'lash havolasi"
          className={`${controlBase} intel-code h-8 min-w-0 flex-1 basis-40 px-2.5 text-xs`}
        />
        <Button size="sm" icon={copied ? Check : Copy} onClick={copy} aria-live="polite">
          {copied ? 'Nusxalandi' : 'Nusxalash'}
        </Button>
        <a href={link.deepLink} target="_blank" rel="noreferrer noopener" className={buttonClasses({ variant: 'primary', size: 'sm' })}>
          <ExternalLink size={15} aria-hidden="true" />
          Ochish
        </a>
      </div>
      {copyFailed && (
        <p role="alert" className="mt-2 text-[11px] font-medium text-danger">
          Nusxalab bo'lmadi (brauzer ruxsat bermadi) — havola belgilandi, Ctrl+C bilan nusxalang.
        </p>
      )}
      <p className="mt-2 text-[11px] text-muted">
        Bot: <span className="intel-code">@{link.botUsername}</span>. Havola bir martalik — ishlatilgach yangisini yarating.
      </p>
    </div>
  );
}
