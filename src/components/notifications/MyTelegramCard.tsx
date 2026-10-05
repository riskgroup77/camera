import { useEffect, useRef, useState } from 'react';
import { Link2, RefreshCw, Unlink } from 'lucide-react';
import { Button, CodeText, ErrorState, IntelPanel, MicroLabel, SkeletonText, StatusLamp } from '../../ui';
import { Notice } from '../settings/kit';
import TelegramLinkBox from './TelegramLinkBox';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useApiResource } from '../../lib/useApiResource';
import { formatUzPhone, notificationsApi, type MyNotifications, type TelegramLink } from '../../lib/notificationsApi';

/** "Mening Telegramim" — shaxsiy bildirishnomalar (tayinlangan hodisa,
 *  muddati o'tgan hodisa) uchun o'z hisobini botga bog'lash. */
export default function MyTelegramCard() {
  const { token } = useAuth();
  const { data, loading, error: loadError, reload } = useApiResource<MyNotifications>('/api/notifications/me');
  const [link, setLink] = useState<TelegramLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // "Bog'ladim — holatni tekshirish" bosilganda, agar hali bog'lanmagan
  // bo'lsa, EKRANDA HECH NARSA O'ZGARMASDI — tugma buzuq deb o'ylanardi.
  // Javob kelgach natijani aytamiz.
  const [checkRequested, setCheckRequested] = useState(false);
  const [checkMessage, setCheckMessage] = useState<string | null>(null);
  const lastData = useRef(data);

  useEffect(() => {
    if (lastData.current === data) return; // yangi javob kelmadi
    lastData.current = data;
    if (!checkRequested) return;
    setCheckRequested(false);
    setCheckMessage(
      data?.telegramLinked ? null : "Bog'lanmagan — havolani oching va «Start» ni bosing.",
    );
  }, [data, checkRequested]);

  function checkStatus() {
    setCheckMessage(null);
    setCheckRequested(true);
    reload();
  }

  async function createLink() {
    setBusy(true);
    setError(null);
    setCheckMessage(null);
    try {
      setLink(await notificationsApi.linkMyTelegram(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      await notificationsApi.unlinkMyTelegram(token);
      setLink(null);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setBusy(false);
    }
  }

  let body;
  if (loading && !data) {
    body = (
      <div className="px-3 py-3">
        <SkeletonText lines={3} />
      </div>
    );
  } else if (data) {
    body = (
      <div className="flex flex-col">
        <dl className="divide-y divide-border border-b border-border">
          <div className="flex items-center gap-4 px-3 py-2">
            <dt className="basis-32 shrink-0">
              <MicroLabel>Telegram</MicroLabel>
            </dt>
            <dd className="min-w-0 flex-1">
              <StatusLamp status={data.telegramLinked ? 'ok' : 'idle'} label={data.telegramLinked ? "Bog'langan" : "Bog'lanmagan"} />
            </dd>
          </div>
          <div className="flex items-center gap-4 px-3 py-2">
            <dt className="basis-32 shrink-0">
              <MicroLabel>Zaxira kanal</MicroLabel>
            </dt>
            <dd className="min-w-0 flex-1 text-[13px] text-fg">
              {data.phone ? <CodeText>{formatUzPhone(data.phone)}</CodeText> : <span className="text-muted">Raqam yo&apos;q</span>}
            </dd>
          </div>
        </dl>

        <div className="flex flex-col gap-2 px-3 py-3">
          <p className="text-[13px] leading-5 text-muted">
            Sizga tayinlangan va muddati o&apos;tgan hodisalar haqida shaxsiy xabar keladi. Telegram bog&apos;lanmagan bo&apos;lsa — SMS.
          </p>
          {data.telegramLinked ? (
            <Button size="sm" variant="ghost" icon={Unlink} onClick={() => void unlink()} loading={busy} className="self-start text-danger hover:text-danger">
              Uzish
            </Button>
          ) : !data.telegramBotConfigured ? (
            <Notice tone="neutral">Telegram bot sozlanmagan.</Notice>
          ) : link ? (
            <>
              <TelegramLinkBox link={link} />
              <Button icon={RefreshCw} onClick={checkStatus} loading={loading} fullWidth>
                Bog&apos;ladim — holatni tekshirish
              </Button>
              {checkMessage && <Notice tone="warning">{checkMessage}</Notice>}
            </>
          ) : (
            <Button variant="primary" icon={Link2} onClick={() => void createLink()} loading={busy} fullWidth>
              Telegramni bog&apos;lash
            </Button>
          )}
          {error && <Notice tone="danger">{error}</Notice>}
        </div>
      </div>
    );
  } else {
    body = <ErrorState variant="block" message={loadError ?? "Yuklab bo'lmadi"} onRetry={reload} />;
  }

  return (
    <IntelPanel
      title="Mening Telegramim"
      brackets={false}
      right={
        data && !loading ? (
          <Button size="sm" variant="ghost" icon={RefreshCw} onClick={reload}>
            Yangilash
          </Button>
        ) : undefined
      }
    >
      {body}
    </IntelPanel>
  );
}
