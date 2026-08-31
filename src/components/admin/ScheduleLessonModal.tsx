import { useEffect, useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useFaculties } from '../../lib/useFaculties';
import { useGroups } from '../../lib/useGroups';
import { useTeachers } from '../../lib/useTeachers';
import { useCameras } from '../../lib/useCameras';
import { toLocalDateString } from '../../lib/date';
import type { LessonSession } from '../../types';

interface FormState {
  date: string;
  group: string;
  faculty: string;
  subject: string;
  teacherId: string;
  cameraId: string;
  scheduledStartTime: string;
}

function todayIso(): string {
  return toLocalDateString(new Date());
}

function toForm(s?: LessonSession | null): FormState {
  return {
    date: s?.date ?? todayIso(),
    group: s?.group ?? '',
    faculty: s?.faculty ?? '',
    subject: s?.subject ?? '',
    teacherId: s?.teacherId ?? '',
    cameraId: s?.cameraId ?? '',
    // datetime-local input expects "YYYY-MM-DDTHH:mm" — trim any seconds/timezone suffix.
    scheduledStartTime: s?.scheduledStartTime ? s.scheduledStartTime.slice(0, 16) : '',
  };
}

/** Handles BOTH flows: no `session` prop → creates a brand-new (scheduled)
 * LessonSession row via POST; `session` given → only attaches/changes the
 * schedule (teacher/camera/start time) on that existing row via the
 * PATCH .../schedule endpoint, since date/group/faculty/subject are already
 * fixed once a monitoring record exists. */
export default function ScheduleLessonModal({
  open,
  session,
  onClose,
  onSave,
}: {
  open: boolean;
  session?: LessonSession | null;
  onClose: () => void;
  onSave: (session: LessonSession) => void;
}) {
  const { token } = useAuth();
  const { faculties } = useFaculties();
  const { groups } = useGroups();
  const { teachers } = useTeachers();
  const { cameras } = useCameras();
  const isReschedule = !!session;
  const [form, setForm] = useState<FormState>(toForm(session));
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>> & { form?: string }>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(toForm(session));
      setErrors({});
    }
  }, [open, session]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  const groupOptions = groups.filter((g) => !form.faculty || g.faculty === form.faculty);

  function validate(): boolean {
    const next: typeof errors = isReschedule
      ? {}
      : {
          date: required(form.date, 'Sana kiritilishi shart'),
          group: required(form.group, 'Guruh kiritilishi shart'),
          faculty: form.faculty ? undefined : 'Fakultetni tanlang',
          subject: required(form.subject, 'Fan nomi kiritilishi shart'),
          teacherId: form.teacherId ? undefined : "O'qituvchini tanlang",
        };
    setErrors(next);
    return !Object.values(next).some(Boolean);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!validate()) return;

    setSaving(true);
    setErrors((prev) => ({ ...prev, form: undefined }));
    try {
      const scheduledStartTime = form.scheduledStartTime || null;
      const saved = isReschedule
        ? await api.patch<LessonSession>(
            `/api/lesson-sessions/${session!.id}/schedule`,
            {
              teacherId: form.teacherId || null,
              cameraId: form.cameraId || null,
              scheduledStartTime,
            },
            token,
          )
        : await api.post<LessonSession>(
            '/api/lesson-sessions',
            {
              date: form.date,
              group: form.group.trim(),
              faculty: form.faculty,
              subject: form.subject.trim(),
              teacherId: form.teacherId,
              cameraId: form.cameraId || null,
              scheduledStartTime,
            },
            token,
          );
      onSave(saved);
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isReschedule ? 'Dars jadvalini belgilash' : 'Yangi dars rejalashtirish'}
      maxWidth="max-w-md"
    >
      <form onSubmit={handleSave} noValidate className="flex flex-col gap-4">
        {errors.form && (
          <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {errors.form}
          </p>
        )}

        {isReschedule ? (
          <p className="-mt-1 rounded-xl bg-indigo-50 px-3 py-2.5 text-xs font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
            {session!.group} / {session!.subject} ({session!.date})
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <TextField
                label="Sana"
                type="date"
                value={form.date}
                onChange={(e) => set('date', e.target.value)}
                error={errors.date}
              />
              <SelectField
                label="Fakultet"
                placeholder="Tanlang"
                value={form.faculty}
                onChange={(e) => {
                  set('faculty', e.target.value);
                  set('group', '');
                }}
                error={errors.faculty}
                options={faculties.map((f) => ({ value: f.name, label: f.name }))}
              />
            </div>
            <div>
              <TextField
                label="Guruh"
                placeholder="IT-21"
                value={form.group}
                onChange={(e) => set('group', e.target.value)}
                error={errors.group}
                list="lesson-group-options"
              />
              <datalist id="lesson-group-options">
                {groupOptions.map((g) => (
                  <option key={g.id} value={g.name} />
                ))}
              </datalist>
            </div>
            <TextField
              label="Fan"
              placeholder="Ma'lumotlar bazasi"
              value={form.subject}
              onChange={(e) => set('subject', e.target.value)}
              error={errors.subject}
            />
            <SelectField
              label="O'qituvchi"
              placeholder="Tanlang"
              value={form.teacherId}
              onChange={(e) => set('teacherId', e.target.value)}
              error={errors.teacherId}
              options={teachers.map((t) => ({ value: t.id, label: t.fullName }))}
            />
          </>
        )}

        <SelectField
          label="Kamera (ixtiyoriy)"
          placeholder="Kuzatuv uchun tanlanmagan"
          value={form.cameraId}
          onChange={(e) => set('cameraId', e.target.value)}
          options={cameras.map((c) => ({ value: c.id, label: `${c.name} (${c.zone})` }))}
        />
        <TextField
          label="Boshlanish vaqti (ixtiyoriy)"
          type="datetime-local"
          value={form.scheduledStartTime}
          onChange={(e) => set('scheduledStartTime', e.target.value)}
        />
        <p className="-mt-2 text-[11px] text-slate-400 dark:text-slate-500">
          Kamera va vaqt belgilansa, tizim darsni avtomatik kuzatadi: o'qituvchining vaqtida kelishi (#22), talaba
          diqqati (#19) va o'qituvchi faolligi (#21).
        </p>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-glass">
            Bekor qilish
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? 'Saqlanmoqda...' : 'Saqlash'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
