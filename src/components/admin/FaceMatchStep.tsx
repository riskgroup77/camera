import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, RotateCcw, XCircle } from 'lucide-react';
import { compareFaces, type FaceMatchResult } from '../../lib/faceMatch';
import { useAuth } from '../../lib/auth';

interface FaceMatchStepProps {
  passportPhotoUrl: string;
  capturedFaceUrl: string;
  onRetake: () => void;
  onResult: (score: number, passed: boolean) => void;
}

export default function FaceMatchStep({
  passportPhotoUrl,
  capturedFaceUrl,
  onRetake,
  onResult,
}: FaceMatchStepProps) {
  const { token } = useAuth();
  const [result, setResult] = useState<FaceMatchResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    compareFaces(capturedFaceUrl, passportPhotoUrl, token).then((r) => {
      if (!cancelled) {
        setResult(r);
        onResult(r.confidence, r.matched);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capturedFaceUrl, passportPhotoUrl]);

  const score = result?.confidence ?? null;
  const passed = result?.matched ?? false;

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="flex items-center gap-4">
        <div className="flex flex-col items-center gap-1.5">
          <img
            src={capturedFaceUrl}
            alt="Jonli surat"
            className="h-32 w-24 rounded-xl border border-white/80 dark:border-white/10 object-cover shadow-btn"
          />
          <span className="text-[11px] text-slate-400 dark:text-slate-500">Jonli surat</span>
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <img
            src={passportPhotoUrl}
            alt="Pasport sahifasi"
            className="h-32 w-24 rounded-xl border border-white/80 dark:border-white/10 object-cover shadow-btn"
          />
          <span className="text-[11px] text-slate-400 dark:text-slate-500">Pasport</span>
        </div>
      </div>

      {score === null ? (
        <div className="flex items-center gap-2 text-sm font-medium text-slate-500 dark:text-slate-400">
          <Loader2 size={16} className="animate-spin" />
          Yuzlar solishtirilmoqda...
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <div
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold ${
              passed ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400'
            }`}
          >
            {passed ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
            {result?.message ? result.message : `${passed ? 'Moslik tasdiqlandi' : 'Moslik topilmadi'} — ${score}%`}
          </div>
          {!passed && (
            <>
              <p className="max-w-xs text-center text-xs text-slate-500 dark:text-slate-400">
                {result?.message
                  ? "Pasport yoki jonli suratda aniq ko'rinadigan yuz yo'q — yorug'likni yaxshilab qayta urinib ko'ring"
                  : "Jonli surat pasportdagi rasm bilan yetarlicha mos kelmadi. Yorug'likni yaxshilab, yuzni oval markaziga joylashtirib qayta urinib ko'ring"}
              </p>
              <button type="button" onClick={onRetake} className="btn-glass flex items-center gap-1.5">
                <RotateCcw size={14} />
                Qayta suratga olish
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
