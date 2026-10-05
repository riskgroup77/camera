import { useCallback, useEffect, useState } from 'react';
import { AlarmClock, ArrowRightLeft, MessageSquare, Send, Sparkles, UserCheck } from 'lucide-react';
import { ErrorState, IconButton, SkeletonText, TONE_SOFT, Textarea, cn } from '../../ui';
import { ApiError, api, isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { relativeTime } from '../../lib/uzDate';
import type { AIEvent, EventTimelineItem } from '../../types';

const MAX_COMMENT = 2000;

const KIND_ICON: Record<EventTimelineItem['kind'], typeof MessageSquare> = {
  yaratildi: Sparkles,
  izoh: MessageSquare,
  holat: ArrowRightLeft,
  tayinlash: UserCheck,
  muddat: AlarmClock,
};

const KIND_TONE: Record<EventTimelineItem['kind'], string> = {
  yaratildi: TONE_SOFT.primary,
  izoh: TONE_SOFT.info,
  holat: TONE_SOFT.success,
  tayinlash: TONE_SOFT.neutral,
  muddat: TONE_SOFT.danger,
};

/** Hodisa tarixi va izohlar: kim, qachon, nima qildi. Hodisa o'zgarganda
 *  (holat, tayinlov, izohlar soni — jumladan boshqa operator tomonidan,
 *  WebSocket orqali) tarix qayta yuklanadi. Boshqa hodisaga o'tilganda
 *  komponent qayta yaratiladi (key={event.id}) — qoralama izoh qolmaydi. */
export default function EventActivity({ event }: { event: AIEvent }) {
  const { token } = useAuth();
  const [items, setItems] = useState<EventTimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // Tarixga ta'sir qiladigan maydonlar — shular o'zgarsa qayta so'raymiz.
  const changeKey = [
    event.id,
    event.status,
    event.assignedToId ?? '',
    event.commentsCount ?? '',
    event.escalatedAt ?? '',
    event.reviewedAt ?? '',
  ].join('|');

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .get<EventTimelineItem[]>(`/api/events/${event.id}/timeline`, token, { signal: controller.signal })
      .then(setItems)
      .catch((err: unknown) => {
        if (!isAbortError(err)) setError(err instanceof ApiError ? err.message : "Tarixni yuklab bo'lmadi");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // changeKey event.id ni ham o'z ichiga oladi.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeKey, token, nonce]);

  const send = useCallback(async () => {
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    setSendError(null);
    try {
      await api.post(`/api/events/${event.id}/comments`, { body }, token);
      setDraft('');
      setNonce((n) => n + 1);
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : "Izohni yuborib bo'lmadi");
    } finally {
      setSending(false);
    }
  }, [draft, sending, event.id, token]);

  return (
    <section className="rounded-card border border-border p-3.5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">Tarix va izohlar</h3>

      {loading && items.length === 0 ? (
        <SkeletonText lines={3} className="py-1" />
      ) : error ? (
        <ErrorState title="Tarixni yuklab bo'lmadi" message={error} onRetry={() => setNonce((n) => n + 1)} />
      ) : (
        <ol className="space-y-2.5">
          {items.map((item) => {
            const Icon = KIND_ICON[item.kind];
            return (
              <li key={item.id} className="flex gap-2.5">
                <span className={cn('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full', KIND_TONE[item.kind])}>
                  <Icon size={12} aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-muted" title={item.at.slice(0, 19).replace('T', ' ')}>
                    {item.authorName ? <span className="font-medium text-fg">{item.authorName}</span> : 'Tizim'}
                    {' · '}
                    {relativeTime(item.at)}
                  </p>
                  <p
                    className={cn(
                      'whitespace-pre-line break-words text-sm text-fg',
                      item.kind === 'izoh' && 'mt-0.5 rounded-control bg-surface-2 px-2.5 py-1.5',
                    )}
                  >
                    {item.body}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <div className="mt-3 flex items-end gap-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value.slice(0, MAX_COMMENT))}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
          aria-label="Izoh yozish"
          placeholder="Izoh… (Ctrl+Enter)"
          className="min-w-0 flex-1 resize-y"
        />
        <IconButton icon={Send} label="Izohni yuborish" variant="primary" onClick={send} disabled={!draft.trim()} loading={sending} />
      </div>
      {sendError && (
        <p role="alert" className="mt-1.5 text-xs font-medium text-danger">
          {sendError}
        </p>
      )}
    </section>
  );
}
