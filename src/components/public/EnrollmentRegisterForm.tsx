import { useEffect, useState } from 'react';
import { UserPlus } from 'lucide-react';
import {
  type EnrollmentFaculty,
  type EnrollmentRegisterInput,
  listEnrollmentFaculties,
} from '../../lib/enrollment';

interface EnrollmentRegisterFormProps {
  /** Qidiruvda kiritilgan pasport — qayta so'ralmaydi. */
  passportSeries: string;
  passportNumber: string;
  onSubmit: (input: EnrollmentRegisterInput) => void;
  onCancel: () => void;
  submitting?: boolean;
}

/**
 * Tizimda yozuvi yo'q odam uchun ro'yxatdan o'tish formasi.
 *
 * Ilgari pasport topilmasa jarayon shu yerda tugardi — "yozuv topilmadi"
 * degan xato chiqib, odam administratorni kutishi kerak edi. Endi u
 * o'zini o'zi kiritadi va darhol yuzini yuklashga o'tadi.
 *
 * Pasport qayta so'ralmaydi: u allaqachon qidiruvda kiritilgan va aynan
 * o'sha qiymatlar bilan yozuv yaratiladi. Qayta terish faqat xato
 * kiritish ehtimolini oshirardi.
 */
export default function EnrollmentRegisterForm({
  passportSeries,
  passportNumber,
  onSubmit,
  onCancel,
  submitting = false,
}: EnrollmentRegisterFormProps) {
  const [fullName, setFullName] = useState('');
  const [type, setType] = useState<'talaba' | 'xodim'>('talaba');
  const [groupOrPosition, setGroupOrPosition] = useState('');
  const [facultyId, setFacultyId] = useState('');
  const [faculties, setFaculties] = useState<EnrollmentFaculty[]>([]);

  // Fakultet ro'yxati bo'lmasa ham forma ishlayveradi — maydon
  // ixtiyoriy, va ro'yxatni yuklab bo'lmagani odamning ro'yxatdan
  // o'tishiga to'sqinlik qilmasligi kerak.
  useEffect(() => {
    let cancelled = false;
    listEnrollmentFaculties()
      .then((rows) => {
        if (!cancelled) setFaculties(rows);
      })
      .catch(() => {
        /* ixtiyoriy maydon — ro'yxatsiz davom etamiz */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const inputClass =
    'w-full rounded-xl border border-white/80 bg-white/60 px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500';

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          fullName: fullName.trim(),
          type,
          groupOrPosition: groupOrPosition.trim(),
          facultyId: facultyId || undefined,
          passportSeries,
          passportNumber,
        });
      }}
      className="flex flex-col gap-4"
    >
      <div className="rounded-xl bg-amber-50 p-3 text-sm leading-relaxed text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
        Bu pasport bo&apos;yicha tizimda yozuv topilmadi. Ma&apos;lumotlaringizni kiriting — ro&apos;yxatdan
        o&apos;tkazamiz.
      </div>

      <div>
        <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">F.I.SH.</label>
        <input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Familiya Ism Sharif"
          required
          minLength={3}
          className={inputClass}
        />
      </div>

      <div>
        <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">Kim sifatida</label>
        <div className="grid grid-cols-2 gap-2">
          {(['talaba', 'xodim'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setType(value)}
              className={`rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors ${
                type === value
                  ? 'bg-indigo-600 text-white shadow-btn'
                  : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10'
              }`}
            >
              {value === 'talaba' ? 'Talaba' : 'Xodim'}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">
          {type === 'talaba' ? 'Guruh' : 'Lavozim'}
        </label>
        <input
          value={groupOrPosition}
          onChange={(e) => setGroupOrPosition(e.target.value)}
          placeholder={type === 'talaba' ? '301-guruh' : 'Laborant'}
          required
          className={inputClass}
        />
      </div>

      {faculties.length > 0 && (
        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">
            Fakultet <span className="font-normal text-slate-400">(ixtiyoriy)</span>
          </label>
          <select value={facultyId} onChange={(e) => setFacultyId(e.target.value)} className={inputClass}>
            <option value="">Tanlanmagan</option>
            {faculties.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="rounded-xl bg-slate-50 px-3 py-2.5 text-xs text-slate-500 dark:bg-white/5 dark:text-slate-400">
        Pasport: <span className="font-semibold text-slate-700 dark:text-slate-200">{passportSeries} {passportNumber}</span>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <UserPlus size={16} />
        {submitting ? 'Saqlanmoqda...' : "Ro'yxatdan o'tish"}
      </button>

      <button
        type="button"
        onClick={onCancel}
        className="text-xs font-medium text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
      >
        Boshqa pasport bilan qayta urinish
      </button>
    </form>
  );
}
