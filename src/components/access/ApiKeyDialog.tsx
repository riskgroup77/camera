import { useState } from 'react';
import { Check, Copy, KeyRound } from 'lucide-react';
import { Button, MicroLabel, Modal, cn } from '../../ui';
import { Notice } from '../settings/kit';
import { webhookUrl } from '../../lib/integrationsApi';
import { copyText } from './clipboard';

function CopyRow({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const [copied, setCopied] = useState(false);
  // Nusxalash muvaffaqiyatsiz tugashi mumkin (HTTP, brauzer ruxsati yo'q) —
  // ilgari bunda MUTLAQO hech narsa ko'rinmasdi: foydalanuvchi "Nusxa"ni
  // bosib, kalit buferga tushgan deb o'ylab oynani yopardi va kalitni
  // butunlay yo'qotardi (u qayta ko'rsatilmaydi).
  const [failed, setFailed] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <MicroLabel>{label}</MicroLabel>
      <div className="flex items-center gap-2">
        <code
          className={cn(
            'intel-code min-w-0 flex-1 break-all border border-border bg-surface-2 px-3 py-2 text-xs',
            secret ? 'text-primary' : 'text-fg',
          )}
        >
          {value}
        </code>
        <Button
          size="sm"
          icon={copied ? Check : Copy}
          aria-label={`${label} — nusxa olish`}
          onClick={async () => {
            const ok = await copyText(value);
            setFailed(!ok);
            if (ok) {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            }
          }}
        >
          {copied ? 'Olindi' : 'Nusxa'}
        </Button>
      </div>
      <p role="status" aria-live="polite" className="sr-only">
        {copied ? `${label} nusxalandi` : ''}
      </p>
      {failed && (
        <p role="alert" className="text-xs font-medium text-danger">
          Nusxalab bo'lmadi — matnni belgilab, Ctrl+C bilan qo'lda ko'chiring.
        </p>
      )}
    </div>
  );
}

/** API kalit faqat shu oynada, bir marta ko'rsatiladi — serverda faqat xeshi saqlanadi. */
export default function ApiKeyDialog({
  open,
  deviceName,
  apiKey,
  webhookPath,
  onClose,
}: {
  open: boolean;
  deviceName: string;
  apiKey: string;
  webhookPath: string;
  onClose: () => void;
}) {
  const url = webhookUrl(webhookPath);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Webhook API kaliti"
      description={deviceName}
      size="lg"
      dismissible={false}
      footer={
        <Button variant="primary" onClick={onClose}>
          Saqladim, yopish
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <Notice tone="warning" icon={KeyRound}>
          <b>{deviceName}</b> uchun kalit. Uni hozir nusxalab, qurilma yoki oraliq dastur sozlamasiga kiriting —{' '}
          <b>bu oyna yopilgach kalit qayta ko'rsatilmaydi</b>. Yo'qotilsa, “Kalitni almashtirish” orqali yangisi beriladi
          (eskisi darhol ishlamay qoladi).
        </Notice>
        <CopyRow label="Webhook manzili (POST)" value={url} />
        <CopyRow label="X-Api-Key sarlavhasi" value={apiKey} secret />
        <div className="border border-border bg-surface-2 px-3 py-2.5 text-xs text-muted">
          <p className="mb-1"><MicroLabel>So&apos;rov namunasi</MicroLabel></p>
          <pre className="intel-code overflow-x-auto whitespace-pre text-[11px] text-fg">{`POST ${url}
X-Api-Key: <kalit>
Content-Type: application/json

{"events": [{"id": "123", "time": "2026-09-19T08:05:00+05:00",
             "cardNo": "0012345", "direction": "kirish", "granted": true}]}`}</pre>
        </div>
      </div>
    </Modal>
  );
}
