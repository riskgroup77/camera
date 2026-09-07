import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ImagePlus, RotateCcw, UploadCloud } from 'lucide-react';

const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp'];

interface EnrollmentPhotoUploadProps {
  onSubmit: (photo: Blob) => void;
  submitting?: boolean;
}

/**
 * Yuzni tasdiqlash uchun tayyor rasmni yuklash.
 *
 * Kameradan uch burchakli suratga olish (avvalgi EnrollmentFaceScan)
 * o'rniga ishlatiladi. Farqi shunchaki qulaylik emas:
 *
 *  - kamera ruxsati talab qilinmaydi, ya'ni brauzer ruxsat bermagan yoki
 *    kamerasi yo'q qurilmada ham ro'yxatdan o'tish mumkin;
 *  - odam o'zi ko'rib, ma'qullagan rasmini yuboradi.
 *
 * Buning evaziga dalil KUCHSIZROQ bo'ladi: yuklangan rasmni boshqa
 * odamniki bilan almashtirib bo'ladi, jonli suratga olishni esa
 * bunchalik oson emas. Bu ataylab qabul qilingan mahsulot qarori.
 *
 * Rasm yuborilishidan oldin ko'rsatiladi — foydalanuvchi nimani
 * yuborayotganini ko'rishi kerak, ayniqsa u biometrik ma'lumot bo'lgani
 * uchun.
 */
export default function EnrollmentPhotoUpload({ onSubmit, submitting = false }: EnrollmentPhotoUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Ko'rish uchun yaratilgan blob: URL brauzer xotirasida qoladi, shuning
  // uchun rasm almashtirilganda yoki komponent yopilganda bo'shatiladi.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function pick(selected: File | undefined) {
    setError(null);
    if (!selected) return;

    // Tekshiruvlar backendda ham bor; bu yerdagisi shunchaki xatoni
    // 10 MB yuklab bo'lgandan keyin emas, darhol aytish uchun.
    if (!ACCEPTED.includes(selected.type)) {
      setError('Faqat JPG, PNG yoki WEBP rasm yuklash mumkin');
      return;
    }
    if (selected.size > MAX_BYTES) {
      setError('Rasm hajmi 10 MB dan oshmasligi kerak');
      return;
    }
    setFile(selected);
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Yuzingiz aks etgan rasmni yuklang</p>
        <p className="mt-1 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          Yuzingiz to&apos;liq va aniq ko&apos;rinib tursin: to&apos;g&apos;riga qaragan, yorug&apos; joyda olingan,
          ko&apos;zoynak yoki niqob bilan yopilmagan rasm eng yaxshi natija beradi.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-600 dark:bg-red-500/10 dark:text-red-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED.join(',')}
        onChange={(e) => pick(e.target.files?.[0])}
        className="hidden"
      />

      {previewUrl ? (
        <div className="flex flex-col gap-3">
          <div className="overflow-hidden rounded-2xl border border-white/80 bg-slate-900 dark:border-white/10">
            <img src={previewUrl} alt="Yuklangan rasm" className="max-h-72 w-full object-contain" />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={submitting}
              className="btn-glass flex flex-1 items-center justify-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw size={15} />
              Boshqa rasm
            </button>
            <button
              type="button"
              onClick={() => file && onSubmit(file)}
              disabled={submitting || !file}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <UploadCloud size={15} />
              {submitting ? 'Saqlanmoqda...' : 'Tasdiqlash'}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-slate-300 px-4 py-10 text-slate-500 transition-colors hover:border-indigo-400 hover:text-indigo-500 dark:border-white/15 dark:text-slate-400 dark:hover:border-indigo-400"
        >
          <ImagePlus size={28} />
          <span className="text-sm font-semibold">Rasm tanlash</span>
          <span className="text-xs">JPG, PNG yoki WEBP · 10 MB gacha</span>
        </button>
      )}
    </div>
  );
}
