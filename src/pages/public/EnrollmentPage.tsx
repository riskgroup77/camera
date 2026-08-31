import { useState } from 'react';
import { AlertTriangle, CheckCircle2, IdCard, ScanFace, UserCheck } from 'lucide-react';
import EnrollmentFaceScan from '../../components/public/EnrollmentFaceScan';
import { ApiError } from '../../lib/apiClient';
import { type EnrollmentLookupResult, lookupByPassport, submitEnrollment } from '../../lib/enrollment';

type Step = 'passport' | 'confirm' | 'scan' | 'success';

export default function EnrollmentPage() {
  const [step, setStep] = useState<Step>('passport');
  const [series, setSeries] = useState('');
  const [number, setNumber] = useState('');
  const [found, setFound] = useState<EnrollmentLookupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await lookupByPassport(series, number);
      setFound(result);
      setStep('confirm');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "So'rovni bajarib bo'lmadi");
    } finally {
      setLoading(false);
    }
  }

  async function handleScanComplete(frames: Blob[]) {
    if (!found) return;
    setError(null);
    setLoading(true);
    try {
      await submitEnrollment(found.recordId, series, number, frames);
      setStep('success');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Yuzni saqlab bo'lmadi");
      setStep('confirm');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 pb-10 pt-4">
      <div className="glass rounded-2xl p-6">
        <div className="mb-5 flex items-center gap-2">
          <ScanFace size={20} className="text-indigo-500" />
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Yuzni ro'yxatdan o'tkazish</h2>
        </div>

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-600 dark:bg-red-500/10 dark:text-red-400">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {step === 'passport' && (
          <form onSubmit={handleLookup} className="flex flex-col gap-4">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Tizimda mavjud yozuvingizni topish uchun pasport seriyasi va raqamingizni kiriting.
            </p>
            <div className="grid grid-cols-3 gap-2">
              <div className="col-span-1">
                <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">Seriya</label>
                <input
                  value={series}
                  onChange={(e) => setSeries(e.target.value.toUpperCase())}
                  placeholder="AD"
                  maxLength={4}
                  required
                  className="w-full rounded-xl border border-white/80 bg-white/60 px-3 py-2.5 text-sm uppercase text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
                />
              </div>
              <div className="col-span-2">
                <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">Raqam</label>
                <input
                  value={number}
                  onChange={(e) => setNumber(e.target.value.replace(/\D/g, ''))}
                  placeholder="1234567"
                  maxLength={10}
                  required
                  className="w-full rounded-xl border border-white/80 bg-white/60 px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <IdCard size={16} />
              {loading ? 'Qidirilmoqda...' : 'Davom etish'}
            </button>
          </form>
        )}

        {step === 'confirm' && found && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 rounded-xl bg-slate-50 p-4 dark:bg-white/5">
              <UserCheck size={22} className="shrink-0 text-emerald-500" />
              <div>
                <p className="text-sm font-bold text-slate-900 dark:text-slate-100">{found.fullName}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {found.typeLabel} · {found.groupOrPosition}
                </p>
              </div>
            </div>

            {found.alreadyEnrolled ? (
              <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
                Siz allaqachon ro'yxatdan o'tgansiz. O'zgartirish kerak bo'lsa, administratorga murojaat qiling.
              </p>
            ) : (
              <>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Bu siz ekanligingizni tasdiqlab, yuzingizni skanerlashga o'ting.
                </p>
                <button
                  type="button"
                  onClick={() => setStep('scan')}
                  className="flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700"
                >
                  <ScanFace size={16} />
                  Ha, bu men — davom etish
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => {
                setStep('passport');
                setFound(null);
              }}
              className="text-xs font-medium text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
            >
              Boshqa ma'lumot bilan qayta urinish
            </button>
          </div>
        )}

        {step === 'scan' && (
          <div className="flex flex-col gap-4">
            {loading ? (
              <div className="flex flex-col items-center gap-2 py-10 text-sm text-slate-500 dark:text-slate-400">
                Saqlanmoqda...
              </div>
            ) : (
              <EnrollmentFaceScan onComplete={handleScanComplete} />
            )}
          </div>
        )}

        {step === 'success' && found && (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <CheckCircle2 size={40} className="text-emerald-500" />
            <p className="text-sm font-bold text-slate-900 dark:text-slate-100">Muvaffaqiyatli saqlandi!</p>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {found.fullName}, yuzingiz endi kameralar orqali tanib olinadi.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
