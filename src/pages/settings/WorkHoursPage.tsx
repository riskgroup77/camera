import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import {
  Button,
  CodeText,
  ErrorState,
  Field,
  Input,
  IntelPanel,
  MicroLabel,
  Page,
  Skeleton,
  StatusLamp,
  cn,
  focusRing,
  useToast,
} from '../../ui';
import { Notice } from '../../components/settings/kit';
import HolidaysPanel from '../../components/settings/HolidaysPanel';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import {
  addMinutes,
  getAttendancePolicy,
  saveAttendancePolicy,
  validateAttendancePolicy,
  type AttendancePolicyErrors,
  type AttendancePolicyInput,
} from '../../lib/attendancePolicyApi';

/** ISO hafta kuni: qisqartma (tugmada) va to'liq nomi (ekran o'quvchi
 *  va sichqoncha izohi uchun — "Pa" nimani anglatishi ko'rinmasdi). */
const DAYS: [number, string, string][] = [
  [1, 'Du', 'Dushanba'],
  [2, 'Se', 'Seshanba'],
  [3, 'Ch', 'Chorshanba'],
  [4, 'Pa', 'Payshanba'],
  [5, 'Ju', 'Juma'],
  [6, 'Sh', 'Shanba'],
  [7, 'Ya', 'Yakshanba'],
];

/** Server saqlangandan keyin oxirgi shuncha kundagi yozuvlarni qayta
 *  hisoblaydi (camera-api/app/routers/attendance_policy.py:RECOMPUTE_DAYS). */
const RECOMPUTE_DAYS = 60;

const BREADCRUMBS = [{ label: 'Sozlamalar' }, { label: 'Ish vaqti' }];

export default function WorkHoursPage() {
  const { token, role } = useAuth();
  const { can } = usePermissions();
  const toast = useToast();
  const canEdit = can('manageAttendance', role);
  const [form, setForm] = useState<AttendancePolicyInput | null>(null);
  /** Serverdan kelgan asl nusxa — "o'zgardimi?" shundan aniqlanadi. */
  const [saved, setSaved] = useState<AttendancePolicyInput | null>(null);
  const [errors, setErrors] = useState<AttendancePolicyErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [nonce, setNonce] = useState(0);
  /** "Saqlash" bosilgandan keyingi tasdiq bosqichi — saqlash serverda
   *  oxirgi 60 kundagi yozuvlarni QAYTA HISOBLAYDI, ya'ni allaqachon
   *  ko'rilgan hisobotlardagi "keldi/kech keldi" o'zgarishi mumkin.
   *  Ilgari bu og'ir amal bitta bosishdan ogohlantirishsiz ketardi. */
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    // So'rov javobi kech kelganda (token almashdi yoki sahifa yopildi)
    // eski qoida formani bosib ketmasin.
    let alive = true;
    getAttendancePolicy(token)
      .then((p) => {
        if (!alive) return;
        const next: AttendancePolicyInput = {
          staffStart: p.staffStart,
          studentStart: p.studentStart,
          graceMinutes: p.graceMinutes,
          workEnd: p.workEnd,
          workDays: p.workDays,
          trackLastSeen: p.trackLastSeen,
        };
        setForm(next);
        setSaved(next);
        setErrors({});
        setError(null);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err instanceof ApiError ? err.message : "Qoidani yuklab bo'lmadi");
      });
    return () => {
      alive = false;
    };
  }, [token, nonce]);

  /** Saqlanmagan o'zgarish bormi — hook'lar erta `return`dan oldin
   *  chaqirilishi shart, shuning uchun shu yerda hisoblanadi. */
  const dirty = form !== null && saved !== null && JSON.stringify(saved) !== JSON.stringify(form);

  // Saqlamay chiqib ketilsa ogohlantiriladi: sahifada boshqa hech qanday
  // avtosaqlash yo'q, yopilgan tab bilan qoida o'zgarishi yo'qolardi.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  // Sarlavha uchta holatda ham bir xil — aks holda yuklanishdan
  // yuklangan holatga o'tganda sahifa boshi sakrardi.
  if (error) {
    return (
      <Page title="Ish vaqti" breadcrumbs={BREADCRUMBS}>
        <ErrorState message={error} onRetry={() => setNonce((n) => n + 1)} />
      </Page>
    );
  }
  if (!form) {
    return (
      <Page title="Ish vaqti" breadcrumbs={BREADCRUMBS}>
        <Skeleton className="h-80" />
      </Page>
    );
  }

  const current = form;
  const set = (patch: Partial<AttendancePolicyInput>) => {
    // Qiymat o'zgardi — avval so'ralgan tasdiq endi boshqa qoidaga
    // tegishli bo'lardi, shuning uchun bekor qilinadi.
    setConfirming(false);
    setForm({ ...current, ...patch });
  };
  const staffLate = addMinutes(current.staffStart, current.graceMinutes);
  const studentLate = addMinutes(current.studentStart, current.graceMinutes);

  /** Birinchi bosish — tekshirish va tasdiq so'rash; ikkinchisi — saqlash. */
  function requestSave() {
    const found = validateAttendancePolicy(current);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setConfirming(false);
      toast.error("Qoida saqlanmadi — qizil bilan belgilangan maydonlarni to'g'rilang");
      return;
    }
    setConfirming(true);
  }

  async function save() {
    const found = validateAttendancePolicy(current);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setConfirming(false);
      toast.error("Qoida saqlanmadi — qizil bilan belgilangan maydonlarni to'g'rilang");
      return;
    }
    setSaving(true);
    try {
      const res = await saveAttendancePolicy(token, current);
      setSaved(current);
      setConfirming(false);
      toast.success(
        res.recomputed
          ? `Saqlandi. Oxirgi ${RECOMPUTE_DAYS} kundagi ${res.recomputed} ta yozuv yangi qoida bo'yicha qayta hisoblandi`
          // "Saqlandi" ning o'zi savol tug'dirardi: qayta hisoblash
          // ishladimi yoki yo'qmi bilinmasdi.
          : `Saqlandi. Oxirgi ${RECOMPUTE_DAYS} kunda o'zgartirish talab qiladigan yozuv topilmadi`,
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Saqlab bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Page
      title="Ish vaqti"
      breadcrumbs={BREADCRUMBS}
      actions={
        <span title={canEdit ? undefined : "Davomat huquqi yo'q"}>
          <Button variant="primary" icon={Save} loading={saving} disabled={!canEdit || !dirty} onClick={requestSave}>
            Saqlash
          </Button>
        </span>
      }
    >
      {!canEdit && (
        <Notice tone="neutral">Faqat ko&apos;rish — &quot;Davomat&quot; huquqi kerak.</Notice>
      )}

      {/* Og'ir amal oldidan tasdiq: saqlash faqat qoidani yozib qo'ymaydi,
          balki oxirgi 60 kundagi davomat yozuvlarini qayta hisoblaydi. */}
      {confirming && !saving && (
        <Notice
          tone="warning"
          title="Saqlashdan oldin tasdiqlang"
          action={
            <span className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => setConfirming(false)}>
                Bekor qilish
              </Button>
              <Button variant="primary" size="sm" onClick={save}>
                Ha, saqlansin
              </Button>
            </span>
          }
        >
          Oxirgi {RECOMPUTE_DAYS} kundagi yozuvlarning holati qayta hisoblanadi. Hisobot va tabeldagi sonlar
          o&apos;zgarishi mumkin.
        </Notice>
      )}

      {/* Qayta hisoblash bir necha soniya davom etishi mumkin — tugmadagi
          aylanma yetarli emas, nima bo'layotgani yozib turiladi. */}
      {saving && (
        <Notice tone="info" title="Saqlanmoqda">
          Yozuvlar qayta hisoblanmoqda — sahifani yopmang.
        </Notice>
      )}
      <IntelPanel title="Qoida" bodyClassName="divide-y divide-border">
          <fieldset disabled={!canEdit} className="grid gap-x-4 gap-y-3 border-0 p-3 sm:grid-cols-2">
            <Field label="Xodimlar ish boshlanishi" error={errors.staffStart}>
              <Input className="intel-code" type="time" value={current.staffStart} onChange={(e) => set({ staffStart: e.target.value })} />
            </Field>
            <Field label="Talabalar dars boshlanishi" error={errors.studentStart}>
              <Input className="intel-code" type="time" value={current.studentStart} onChange={(e) => set({ studentStart: e.target.value })} />
            </Field>
            <Field label="Kechikishga ruxsat (daqiqa)" error={errors.graceMinutes}>
              {/* Qiymat jimgina 0..180 ga "qisib" qo'yilmaydi: ilgari 200
                  yozilsa maydonda 180 paydo bo'lardi va foydalanuvchi o'zi
                  yozgan sonni yo'qotardi. Endi chegara xatosi ko'rsatiladi
                  (validateAttendancePolicy). */}
              <Input
                className="intel-code"
                type="number"
                min={0}
                max={180}
                value={current.graceMinutes}
                invalid={Boolean(errors.graceMinutes)}
                onChange={(e) => {
                  const raw = Number(e.target.value);
                  set({ graceMinutes: Number.isFinite(raw) ? Math.trunc(raw) : 0 });
                }}
              />
            </Field>
            <Field label="Ish tugashi" error={errors.workEnd}>
              <Input className="intel-code" type="time" value={current.workEnd} onChange={(e) => set({ workEnd: e.target.value })} />
            </Field>
          </fieldset>

          <div className="p-3">
            <MicroLabel className="!text-fg">Ish kunlari</MicroLabel>
            <div className="mt-1.5 flex flex-wrap gap-1" role="group" aria-label="Ish kunlari">
              {DAYS.map(([day, label, fullName]) => {
                const on = current.workDays.includes(day);
                return (
                  <button
                    key={day}
                    type="button"
                    aria-pressed={on}
                    aria-label={fullName}
                    disabled={!canEdit}
                    onClick={() =>
                      set({
                        workDays: on
                          ? current.workDays.filter((d) => d !== day)
                          : [...current.workDays, day].sort((a, b) => a - b),
                      })
                    }
                    className={cn(
                      'intel-code h-9 w-11 border text-[13px] font-semibold disabled:opacity-60',
                      on
                        ? 'border-primary bg-primary text-primary-fg'
                        : 'border-border bg-surface-2 text-muted hover:text-fg',
                      focusRing,
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {errors.workDays ? (
              <p role="alert" className="mt-1.5 text-xs font-medium text-danger">
                {errors.workDays}
              </p>
            ) : null}
          </div>

          <label className="flex items-start gap-2.5 p-3 text-[13px] text-fg">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              disabled={!canEdit}
              checked={current.trackLastSeen}
              onChange={(e) => set({ trackLastSeen: e.target.checked })}
            />
            <span className="min-w-0">Ketish vaqtini yozish</span>
          </label>

        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface-2/60 px-3 py-2 text-[13px] text-fg">
          <span>
            Kech keldi: xodim <CodeText className="font-semibold">{staffLate}</CodeText> dan, talaba{' '}
            <CodeText className="font-semibold">{studentLate}</CodeText> dan keyin.
          </span>
          <StatusLamp className="ms-auto" status={dirty ? 'warn' : 'ok'} label={dirty ? 'Saqlanmagan' : 'Kuchda'} />
        </p>
      </IntelPanel>
      <HolidaysPanel token={token} canEdit={canEdit} />
    </Page>
  );
}
