import { useState } from 'react';
import { AlertTriangle, CheckCircle2, IdCard, ScanFace, UserCheck } from 'lucide-react';
import EnrollmentPhotoUpload from '../../components/public/EnrollmentPhotoUpload';
import EnrollmentRegisterForm from '../../components/public/EnrollmentRegisterForm';
import { ApiError } from '../../lib/apiClient';
import {
  type EnrollmentLookupResult,
  type EnrollmentRegisterInput,
  type EnrollmentIdentity,
  lookupPerson,
  registerSelf,
  submitEnrollment,
} from '../../lib/enrollment';

type Step = 'identify' | 'register' | 'confirm' | 'photo' | 'success';

/** Shaxsni aniqlash usuli.
 *
 *  JSHSHIR standart tanlov: institut kadrlar ro'yxati aynan shu raqam
 *  bilan yuritiladi va ommaviy kiritilgan xodimlarda pasport ma'lumoti
 *  umuman yo'q. Pasport yo'li ilgari shu tarzda ro'yxatdan o'tganlar
 *  uchun qoldirilgan. */
type Method = 'pinfl' | 'passport';

export default function EnrollmentPage() {
  const [step, setStep] = useState<Step>('identify');
  const [method, setMethod] = useState<Method>('pinfl');
  const [pinfl, setPinfl] = useState('');
  const [series, setSeries] = useState('');
  const [number, setNumber] = useState('');
  const [found, setFound] = useState<EnrollmentLookupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const identity: EnrollmentIdentity =
    method === 'pinfl'
      ? { kind: 'pinfl', pinfl }
      : { kind: 'passport', passportSeries: series, passportNumber: number };

  async function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await lookupPerson(identity);
      setFound(result);
      setStep('confirm');
    } catch (err) {
      // 404 — bu xato emas, oqimning ikkinchi yo'li: tizimda yozuvi yo'q
      // odam shu yerdan o'zini ro'yxatdan o'tkazadi. Ilgari jarayon
      // aynan shu nuqtada "yozuv topilmadi" bilan tugardi.
      if (err instanceof ApiError && err.status === 404) {
        setStep('register');
      } else {
        setError(err instanceof ApiError ? err.message : "So'rovni bajarib bo'lmadi");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(input: EnrollmentRegisterInput) {
    setError(null);
    setLoading(true);
    try {
      const created = await registerSelf(input);
      setFound(created);
      setStep('confirm');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ro'yxatdan o'tkazib bo'lmadi");
    } finally {
      setLoading(false);
    }
  }

  async function handlePhotoSubmit(photo: Blob) {
    if (!found) return;
    setError(null);
    setLoading(true);
    try {
      await submitEnrollment(found.recordId, identity, [photo]);
      setStep('success');
    } catch (err) {
      // Xato bo'lsa rasm qadamida qolamiz: eng ko'p uchraydigan sabab —
      // rasmda yuz aniqlanmagani, va bunda odam DARHOL boshqa rasm
      // yuklay olishi kerak, boshidan boshlashi emas.
      setError(err instanceof ApiError ? err.message : "Yuzni saqlab bo'lmadi");
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

        {step === 'identify' && (
          <form onSubmit={handleLookup} className="flex flex-col gap-4">
            <p className="text-sm leading-relaxed text-slate-500 dark:text-slate-400">
              Tizimda mavjud yozuvingizni topish uchun JSHSHIR raqamingizni kiriting. U pasportingizning
              ma&apos;lumot sahifasida, 14 raqamdan iborat.
            </p>

            <div className="grid grid-cols-2 gap-2">
              {([
                ['pinfl', 'JSHSHIR'],
                ['passport', 'Pasport'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    setMethod(value);
                    setError(null);
                  }}
                  className={`rounded-xl px-3 py-2 text-sm font-semibold transition-colors ${
                    method === value
                      ? 'bg-indigo-600 text-white shadow-btn'
                      : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {method === 'pinfl' ? (
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">
                  JSHSHIR (14 raqam)
                </label>
                <input
                  value={pinfl}
                  onChange={(e) => setPinfl(e.target.value.replace(/\D/g, '').slice(0, 14))}
                  placeholder="30302654150047"
                  inputMode="numeric"
                  required
                  minLength={13}
                  className="w-full rounded-xl border border-white/80 bg-white/60 px-3 py-2.5 font-mono text-sm tracking-wide text-slate-900 outline-none transition-colors placeholder:font-sans placeholder:tracking-normal placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
                />
                <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
                  Kiritilgan: {pinfl.length}/14 raqam
                </p>
              </div>
            ) : (
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
            )}

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
                  onClick={() => setStep('photo')}
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
                setStep('identify');
                setFound(null);
              }}
              className="text-xs font-medium text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
            >
              Boshqa ma'lumot bilan qayta urinish
            </button>
          </div>
        )}

        {step === 'register' && (
          <EnrollmentRegisterForm
            pinfl={method === 'pinfl' ? pinfl : undefined}
            passportSeries={method === 'passport' ? series : undefined}
            passportNumber={method === 'passport' ? number : undefined}
            onSubmit={handleRegister}
            onCancel={() => {
              setStep('identify');
              setError(null);
            }}
            submitting={loading}
          />
        )}

        {step === 'photo' && (
          <EnrollmentPhotoUpload onSubmit={handlePhotoSubmit} submitting={loading} />
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
