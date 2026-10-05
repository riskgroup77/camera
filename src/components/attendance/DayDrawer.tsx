import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, Clock3, GraduationCap, LogIn, LogOut, MapPin, Trash2 } from 'lucide-react';
import { Badge, Button, ConfirmDialog, Drawer, ErrorState, Field, Input, Select, Skeleton, useToast, type Tone } from '../../ui';
import { ApiError, api, isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { CELL_STATUS_LABEL, CELL_STATUS_TONE, clockToMinutes, dayLabel, type CalendarCell, type CellStatus } from '../../lib/attendanceCalendar';
import { formatMinutes } from '../../lib/uzDate';
import type { AttendanceDay, AttendanceDayStatus, LessonRelation, PersonDay, PresenceVisitItem } from '../../types';

const RELATION_TONE: Record<LessonRelation, Tone> = {
  oz_darsi: 'success',
  boshqa_dars: 'warning',
  darsi_boshqa_joyda: 'danger',
  darsdan_tashqari: 'neutral',
  jadval_yoq: 'neutral',
};

const CELL_TONE: Record<string, Tone> = { green: 'success', amber: 'warning', red: 'danger', slate: 'neutral' };

const STATUS_OPTIONS: { value: AttendanceDayStatus; label: string }[] = [
  { value: 'keldi', label: 'Keldi' },
  { value: 'kech_keldi', label: 'Kech keldi' },
  { value: 'kelmadi', label: 'Kelmadi' },
  { value: 'dam_olish', label: 'Dam olish' },
];

// Kun chizig'i 07:00–20:00 oralig'ini ko'rsatadi; undan tashqaridagi tashriflar chetga yopishadi.
const TRACK_START = 7 * 60;
const TRACK_END = 20 * 60;
const TRACK_HOURS = [8, 10, 12, 14, 16, 18];

function trackPercent(clock: string): number {
  const value = ((clockToMinutes(clock) - TRACK_START) / (TRACK_END - TRACK_START)) * 100;
  return Math.max(0, Math.min(100, value));
}

function isRecordStatus(status: CellStatus): status is AttendanceDayStatus {
  return status !== 'malumot_yoq' && status !== 'kelajak';
}

function DayTrack({ visits }: { visits: PresenceVisitItem[] }) {
  return (
    <div aria-hidden="true">
      <div className="relative h-7 overflow-hidden rounded-control bg-surface-2">
        {TRACK_HOURS.map((hour) => (
          <span key={hour} className="absolute inset-y-0 w-px bg-border" style={{ left: `${trackPercent(`${hour}:00`)}%` }} />
        ))}
        {visits.map((visit, index) => {
          const left = trackPercent(visit.firstSeen);
          const width = Math.max(trackPercent(visit.lastSeen) - left, 0.7);
          return (
            <span
              key={`${visit.firstSeen}-${index}`}
              className="absolute inset-y-1 rounded bg-primary/80"
              style={{ left: `${left}%`, width: `${width}%` }}
            />
          );
        })}
      </div>
      <div className="relative mt-1 h-3 text-[10px] tabular-nums text-subtle">
        {TRACK_HOURS.map((hour) => (
          <span key={hour} className="absolute -translate-x-1/2" style={{ left: `${trackPercent(`${hour}:00`)}%` }}>
            {String(hour).padStart(2, '0')}
          </span>
        ))}
      </div>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-control border border-border bg-surface-2/60 p-2.5">
      <p className="flex items-center gap-1 text-[11px] font-medium text-muted">
        {icon}
        {label}
      </p>
      <p className="mt-0.5 text-base font-semibold tabular-nums text-fg">{value}</p>
    </div>
  );
}

/** Bir kun: davomat, kameralar odamni qayerda va qachon ko'rgani, jadvaldagi
 *  darslari va qo'lda tuzatish (POST/DELETE /api/attendance). ← → bilan
 *  qo'shni kunlarga o'tiladi. */
export default function DayDrawer({
  open,
  personId,
  personName,
  cell,
  onClose,
  onPrev,
  onNext,
  onSaved,
  onDeleted,
  canEdit = true,
}: {
  open: boolean;
  personId: string;
  personName: string;
  cell: CalendarCell | null;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onSaved: (day: AttendanceDay) => void;
  onDeleted: (date: string) => void;
  /** Qo'lda tuzatish formasi (manageAttendance). */
  canEdit?: boolean;
}) {
  const { token } = useAuth();
  const toast = useToast();
  const [detail, setDetail] = useState<PersonDay | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);
  const [status, setStatus] = useState<AttendanceDayStatus>('keldi');
  const [checkIn, setCheckIn] = useState('');
  const [checkOut, setCheckOut] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const date = cell?.date ?? null;

  useEffect(() => {
    if (!open || !date || !token) return;
    const controller = new AbortController();
    setDetail(null);
    setDetailError(null);
    api
      .get<PersonDay>(`/api/presence/people/${personId}/day?date=${date}`, token, { signal: controller.signal })
      .then(setDetail)
      .catch((err: unknown) => {
        if (!isAbortError(err)) setDetailError(err instanceof Error ? err.message : "Ma'lumotni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [open, date, personId, token, detailVersion]);

  useEffect(() => {
    if (!cell) return;
    setStatus(cell.isRecord && isRecordStatus(cell.status) ? cell.status : 'keldi');
    setCheckIn(cell.checkIn ?? '');
    setCheckOut(cell.checkOut ?? '');
    setFormError(null);
  }, [cell]);

  useEffect(() => {
    if (!open) return;
    function onKey(event: globalThis.KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return;
      if (event.key === 'ArrowLeft' && onPrev) {
        event.preventDefault();
        onPrev();
      } else if (event.key === 'ArrowRight' && onNext) {
        event.preventDefault();
        onNext();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onPrev, onNext]);

  const timesAllowed = status === 'keldi' || status === 'kech_keldi';

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!cell || !token) return;
    if (timesAllowed && checkIn && checkOut && checkOut <= checkIn) {
      setFormError("Ketgan vaqt kelgan vaqtdan keyin bo'lishi kerak");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const saved = await api.post<AttendanceDay>(
        '/api/attendance',
        {
          studentStaffId: personId,
          date: cell.date,
          status,
          checkIn: timesAllowed && checkIn ? checkIn : null,
          checkOut: timesAllowed && checkOut ? checkOut : null,
        },
        token,
      );
      onSaved(saved);
      toast.success('Davomat saqlandi');
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Saqlab bo'lmadi — tarmoqni tekshirib, qayta urinib ko'ring");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!cell || !token) return;
    const day = cell.date;
    try {
      await api.del(`/api/attendance/${personId}/${day}`, token);
      onDeleted(day);
      toast.success("Davomat yozuvi o'chirildi");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "O'chirib bo'lmadi — qayta urinib ko'ring");
    } finally {
      setConfirmDelete(false);
    }
  }

  return (
    <>
      <Drawer
        open={open && cell !== null}
        onClose={onClose}
        size="lg"
        title={cell ? dayLabel(cell.date) : ''}
        subtitle={personName}
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <Button size="sm" variant="ghost" icon={ChevronLeft} onClick={onPrev} disabled={!onPrev}>
              Oldingi kun
            </Button>
            <span className="hidden text-[11px] text-subtle sm:inline">← → — kunlar orasida</span>
            <Button size="sm" variant="ghost" iconRight={ChevronRight} onClick={onNext} disabled={!onNext}>
              Keyingi kun
            </Button>
          </div>
        }
      >
        {cell && (
          <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={CELL_TONE[CELL_STATUS_TONE[cell.status]]} dot size="md">
                {CELL_STATUS_LABEL[cell.status]}
              </Badge>
              {cell.earlyLeave && <Badge tone="warning">Erta ketdi</Badge>}
              {cell.status === 'malumot_yoq' && <span className="text-xs text-muted">Yozuv yo'q — bu «kelmadi» degani emas.</span>}
            </div>

            <div className="grid grid-cols-3 gap-2">
              <Metric icon={<LogIn size={11} />} label="Keldi" value={cell.checkIn ?? '—'} />
              <Metric icon={<LogOut size={11} />} label="Ketdi" value={cell.checkOut ?? '—'} />
              <Metric icon={<Clock3 size={11} />} label="Binoda" value={formatMinutes(cell.presenceMinutes)} />
            </div>

            <section>
              <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-fg">
                <MapPin size={15} className="text-primary" />
                Qayerda va qachon ko'ringan
              </h4>
              {detailError ? (
                <ErrorState message={detailError} onRetry={() => setDetailVersion((v) => v + 1)} />
              ) : !detail ? (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-7" />
                  <Skeleton className="h-14" />
                  <Skeleton className="h-14" />
                </div>
              ) : detail.visits.length === 0 ? (
                <p className="rounded-control bg-surface-2 px-3 py-2.5 text-xs text-muted">Bu kunda kameralar uni tanimagan.</p>
              ) : (
                <>
                  <DayTrack visits={detail.visits} />
                  <ol className="mt-3 flex flex-col gap-2 border-l-2 border-primary/20 pl-4">
                    {detail.visits.map((visit, index) => {
                      const from = visit.firstSeen.slice(0, 5);
                      const to = visit.lastSeen.slice(0, 5);
                      return (
                        <li key={`${visit.firstSeen}-${index}`} className="relative rounded-control border border-border px-3 py-2">
                          <span className="absolute -left-[23px] top-3 h-2.5 w-2.5 rounded-full bg-primary ring-2 ring-surface" aria-hidden="true" />
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-sm text-fg">
                              <span className="font-semibold tabular-nums">{from === to ? from : `${from}–${to}`}</span>{' '}
                              <span className="text-xs text-muted">{formatMinutes(visit.durationMinutes)}</span>
                            </span>
                            <Badge tone={RELATION_TONE[visit.lesson.relation]}>{visit.lesson.label}</Badge>
                          </div>
                          <p className="mt-0.5 text-xs text-muted">
                            {visit.building} · {visit.camera} · {visit.cameraRole}
                          </p>
                        </li>
                      );
                    })}
                  </ol>
                </>
              )}
            </section>

            {detail && detail.lessons.length > 0 && (
              <section>
                <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-fg">
                  <GraduationCap size={15} className="text-primary" />
                  Jadvaldagi darslari
                </h4>
                <ul className="flex flex-col gap-1.5">
                  {detail.lessons.map((lesson) => (
                    <li key={`${lesson.startsAt}-${lesson.groupName}`} className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-border px-3 py-2 text-xs">
                      <span className="min-w-0 text-fg">
                        <span className="font-semibold tabular-nums">
                          {lesson.startsAt}–{lesson.endsAt}
                        </span>{' '}
                        {lesson.subject} ({lesson.groupName})
                        <span className="block text-muted">
                          {lesson.camera ?? 'xona kiritilmagan'}
                          {lesson.building ? `, ${lesson.building}` : ''}
                        </span>
                      </span>
                      {lesson.attended ? (
                        <Badge tone={lesson.late ? 'warning' : 'success'}>{lesson.late ? `Kech kirdi · ${lesson.arrivedAt}` : `Kirdi · ${lesson.arrivedAt}`}</Badge>
                      ) : (
                        <Badge tone="danger">Xonada ko'rinmadi</Badge>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {canEdit && (
              <form onSubmit={save} className="rounded-card border border-border bg-surface-2/50 p-4">
                <h4 className="text-sm font-semibold text-fg">Qo'lda tuzatish</h4>
                <p className="mb-3 text-xs text-muted">Kamera xato qilgan yoki tanimagan kunni to'g'rilang. O'zgarish audit jurnaliga yoziladi.</p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <div className="col-span-2 sm:col-span-1">
                    <Field label="Holat">
                      <Select value={status} onChange={(v) => setStatus(v as AttendanceDayStatus)} options={STATUS_OPTIONS} className="sm:w-full" />
                    </Field>
                  </div>
                  <Field label="Keldi">
                    <Input type="time" value={timesAllowed ? checkIn : ''} disabled={!timesAllowed} onChange={(e) => setCheckIn(e.target.value)} />
                  </Field>
                  <Field label="Ketdi">
                    <Input type="time" value={timesAllowed ? checkOut : ''} disabled={!timesAllowed} onChange={(e) => setCheckOut(e.target.value)} />
                  </Field>
                </div>
                {formError && <p className="mt-2 text-xs font-medium text-danger">{formError}</p>}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button type="submit" variant="primary" size="sm" loading={saving}>
                    {cell.isRecord ? 'Saqlash' : "Yozuv qo'shish"}
                  </Button>
                  {cell.isRecord && (
                    <Button variant="ghost" size="sm" icon={Trash2} className="text-danger hover:text-danger" onClick={() => setConfirmDelete(true)}>
                      Yozuvni o'chirish
                    </Button>
                  )}
                </div>
              </form>
            )}
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmDelete}
        title="Davomat yozuvini o'chirish"
        message={cell ? `${personName} uchun ${dayLabel(cell.date)} davomat yozuvini o'chirishni tasdiqlaysizmi?` : ''}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={remove}
      />
    </>
  );
}
