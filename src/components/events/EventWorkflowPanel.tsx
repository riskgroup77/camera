import { useId, useState } from 'react';
import { CheckCircle2, CircleDot, RotateCcw, ShieldAlert, UserCheck, X } from 'lucide-react';
import { Button, Select, useToast, type ButtonVariant } from '../../ui';
import ResolveDialog from './ResolveDialog';
import SlaBadge from './SlaBadge';
import { useAssignees } from './useAssignees';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { STATUS_LABEL } from '../../lib/eventLabels';
import { canAssign, statusActions, type StatusAction } from '../../lib/eventWorkflow';
import type { AIEvent, EventStatus } from '../../types';

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Tarmoq xatosi';
}

const ACTION_ICON: Record<EventStatus, typeof CircleDot> = {
  yangi: RotateCcw,
  jarayonda: CircleDot,
  tasdiqlangan: ShieldAlert,
  rad_etilgan: X,
  hal_qilindi: CheckCircle2,
};

const VARIANT: Record<StatusAction['variant'], ButtonVariant> = {
  primary: 'primary',
  success: 'soft',
  neutral: 'secondary',
};

function formatLocal(iso: string | null | undefined): string | null {
  return iso ? iso.slice(0, 16).replace('T', ' ') : null;
}

/** Ish jarayoni bloki: mas'ul (tayinlash), muddat, holat amallari va yechim.
 *  Har amaldan keyin server qaytargan yangi hodisa `onChanged` ga beriladi. */
export default function EventWorkflowPanel({ event, onChanged }: { event: AIEvent; onChanged: (updated: AIEvent) => void }) {
  const { token } = useAuth();
  const toast = useToast();
  const selectId = useId();
  const assignable = canAssign(event);
  const { assignees, error: assigneesError } = useAssignees(assignable);
  const [pending, setPending] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  async function assign(userId: string | null) {
    setPending('assign');
    try {
      const updated = await api.post<AIEvent>(`/api/events/${event.id}/assign`, { userId }, token);
      onChanged(updated);
      toast.success(userId ? `Tayinlandi: ${updated.assignedToName ?? ''}` : 'Tayinlov olib tashlandi');
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setPending(null);
    }
  }

  async function changeStatus(target: EventStatus, note?: string) {
    setPending(target);
    try {
      const updated = await api.post<AIEvent>(`/api/events/${event.id}/status`, { status: target, note }, token);
      onChanged(updated);
      toast.success(`Holat: ${STATUS_LABEL[updated.status]}`);
    } catch (err) {
      // Yechim dialogi xatoni o'zida ko'rsatadi (ochiq qoladi).
      if (note === undefined) toast.error(errorText(err));
      throw err;
    } finally {
      setPending(null);
    }
  }

  if (event.isTrial) return null;

  const actions = statusActions(event.status);
  // Tanlangan foydalanuvchi ro'yxatda bo'lmasa ham (huquqi olingan) ko'rinsin.
  const options =
    event.assignedToId && !assignees.some((a) => a.id === event.assignedToId)
      ? [{ id: event.assignedToId, fullName: event.assignedToName ?? "Noma'lum", role: '' }, ...assignees]
      : assignees;

  return (
    <section className="space-y-3 rounded-card border border-border bg-surface-2/60 p-3.5" aria-labelledby={`${selectId}-title`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`${selectId}-title`} className="text-xs font-semibold uppercase tracking-wide text-muted">
          Ish jarayoni
        </h3>
        <SlaBadge event={event} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={selectId} className="text-[13px] font-medium text-muted">
          Mas&apos;ul
        </label>
        {assignable ? (
          <>
            <Select
              id={selectId}
              size="sm"
              value={event.assignedToId ?? ''}
              disabled={pending !== null}
              onChange={(value) => assign(value || null)}
              placeholder="— Tayinlanmagan —"
              options={options.map((a) => ({ value: a.id, label: `${a.fullName}${a.role ? ` (${a.role})` : ''}` }))}
              className="min-w-0 flex-1 sm:w-auto"
            />
            <Button size="sm" variant="soft" icon={UserCheck} loading={pending === 'assign'} disabled={pending !== null} onClick={() => assign('me')}>
              Menga
            </Button>
          </>
        ) : (
          <span className="text-sm font-medium text-fg">{event.assignedToName ?? '—'}</span>
        )}
      </div>
      {assigneesError && assignable && <p className="text-xs text-danger">Ro&apos;yxat yuklanmadi</p>}
      {event.assignedAt && event.assignedToName && <p className="text-xs text-muted">Tayinlangan: {formatLocal(event.assignedAt)}</p>}

      {event.status === 'hal_qilindi' && event.resolutionNote && (
        <div className="rounded-control bg-success-soft px-3 py-2">
          <p className="text-xs font-semibold text-success">
            Yechim · {event.resolvedBy ?? ''}
            {event.resolvedAt ? ` · ${formatLocal(event.resolvedAt)}` : ''}
          </p>
          <p className="whitespace-pre-line text-sm text-fg">{event.resolutionNote}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <Button
            key={action.target}
            size="sm"
            variant={VARIANT[action.variant]}
            icon={ACTION_ICON[action.target]}
            loading={pending === action.target}
            disabled={pending !== null}
            onClick={() => {
              if (action.needsNote) setResolving(true);
              else changeStatus(action.target).catch(() => undefined);
            }}
          >
            {action.label}
          </Button>
        ))}
      </div>

      <ResolveDialog
        open={resolving}
        onCancel={() => setResolving(false)}
        onConfirm={async (note) => {
          try {
            await changeStatus('hal_qilindi', note);
          } catch (err) {
            throw new Error(errorText(err));
          }
          setResolving(false);
        }}
      />
    </section>
  );
}
