import type { ReactNode } from 'react';
import { Send } from 'lucide-react';
import { Button, CodeText, ErrorState, IntelPanel, MicroLabel, Skeleton, StatusLamp } from '../../ui';
import type { NotificationStatus } from '../../lib/notificationsApi';

/** Bitta kanal qatori: yorliq, chiroq + SO'Z, ostida tafsilot.
 *  Qator balandligi zich — chiziq bilan ajraladi, oraliq bilan emas. */
function Row({ ok, title, detail }: { ok: boolean; title: string; detail: ReactNode }) {
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-1 px-3 py-2">
      <span className="min-w-0 basis-40">
        <MicroLabel>{title}</MicroLabel>
      </span>
      <StatusLamp status={ok ? 'ok' : 'idle'} label={ok ? 'Sozlangan' : 'Sozlanmagan'} className="shrink-0" />
      <span className="min-w-0 flex-1 basis-56 text-[13px] leading-5 text-muted">{detail}</span>
    </li>
  );
}

/** Kanal holati — faqat o'qiladi. Sozlamalar serverning .env faylida
 *  (TELEGRAM_BOT_TOKEN, SMS_PROVIDER, ESKIZ_*, PARENT_NOTIFY_*). */
export default function NotificationStatusCard({
  status,
  loading,
  onTest,
  error,
  onRetry,
}: {
  status: NotificationStatus | null;
  loading: boolean;
  onTest: () => void;
  error?: string | null;
  onRetry?: () => void;
}) {
  let body: ReactNode;
  if (loading && !status) {
    body = (
      <div className="divide-y divide-border" aria-busy="true" aria-label="Yuklanmoqda">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-4 px-3 py-2.5">
            <Skeleton className="h-3 w-32 shrink-0" />
            <Skeleton className="h-3 flex-1" />
          </div>
        ))}
      </div>
    );
  } else if (status) {
    body = (
      <ul className="divide-y divide-border">
        <Row
          ok={status.telegramConfigured}
          title="Telegram bot"
          detail={
            status.telegramConfigured ? (
              <>
                {status.telegramBotUsername ? <CodeText>@{status.telegramBotUsername}</CodeText> : 'Bot nomi aniqlanmadi'}
                {status.telegramPollingEnabled ? ' · /start yoqilgan' : " · polling o'chiq"}
              </>
            ) : (
              <>
                .env faylida <CodeText className="text-[12px]">TELEGRAM_BOT_TOKEN</CodeText> ni kiriting
              </>
            )
          }
        />
        <Row
          ok={status.smsConfigured}
          title="SMS (Eskiz.uz)"
          detail={
            status.smsConfigured ? (
              <>
                Yuboruvchi: <CodeText className="text-fg">{status.smsSender ?? '—'}</CodeText>
              </>
            ) : (
              <>
                <CodeText className="text-[12px]">SMS_PROVIDER=eskiz</CodeText>, <CodeText className="text-[12px]">ESKIZ_EMAIL</CodeText> va{' '}
                <CodeText className="text-[12px]">ESKIZ_PASSWORD</CodeText>
              </>
            )
          }
        />
        <Row
          ok={status.parentArrivalEnabled || status.parentAbsenceEnabled}
          title="Ota-onalarga xabar"
          detail={
            <>
              <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
                <StatusLamp status={status.parentArrivalEnabled ? 'ok' : 'idle'} label={`Kelganda: ${status.parentArrivalEnabled ? 'yoqilgan' : "o'chiq"}`} />
                <StatusLamp status={status.parentAbsenceEnabled ? 'ok' : 'idle'} label={`Kelmaganda: ${status.parentAbsenceEnabled ? 'yoqilgan' : "o'chiq"}`} />
              </span>
            </>
          }
        />
      </ul>
    );
  } else {
    body = <ErrorState variant="block" message={error ?? "Holatni yuklab bo'lmadi."} onRetry={onRetry} />;
  }

  return (
    <IntelPanel
      title="Kanallar"
      right={
        <Button size="sm" icon={Send} onClick={onTest} disabled={!status}>
          Sinov xabari
        </Button>
      }
    >
      {body}
    </IntelPanel>
  );
}
