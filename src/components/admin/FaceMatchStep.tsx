import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, RotateCcw, XCircle } from 'lucide-react';
import { compareFaces, type FaceMatchResult } from '../../lib/faceMatch';
import { useAuth } from '../../lib/auth';
import { Button, cn } from '../../ui';

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
    compareFaces(capturedFaceUrl, passportPhotoUrl, token)
      .then((r) => {
        if (!cancelled) {
          setResult(r);
          onResult(r.confidence, r.matched);
        }
      })
      .catch((err: unknown) => {
        // Tarmoq/server xatosi — "solishtirilmoqda..." abadiy aylanib qolmasin.
        if (cancelled) return;
        const failed: FaceMatchResult = {
          confidence: 0,
          matched: false,
          method: 'remote-api',
          message: err instanceof Error && err.message ? err.message : "Solishtirib bo'lmadi — tarmoqni tekshiring",
        };
        setResult(failed);
        onResult(0, false);
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
            className="h-32 w-24 rounded-card border border-border object-cover shadow-card"
          />
          <span className="text-[11px] text-muted">Jonli surat</span>
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <img
            src={passportPhotoUrl}
            alt="Pasport sahifasi"
            className="h-32 w-24 rounded-card border border-border object-cover shadow-card"
          />
          <span className="text-[11px] text-muted">Pasport</span>
        </div>
      </div>

      {score === null ? (
        <div className="flex items-center gap-2 text-sm font-medium text-muted" role="status">
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
          Yuzlar solishtirilmoqda...
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <div
            role="status"
            className={cn('flex items-center gap-2 rounded-control px-4 py-2 text-sm font-semibold', passed ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger')}
          >
            {passed ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />}
            {result?.message ? result.message : `${passed ? 'Moslik tasdiqlandi' : 'Moslik topilmadi'} — ${score}%`}
          </div>
          {!passed && (
            <>
              <p className="max-w-xs text-center text-xs text-muted">
                {result?.message
                  ? "Pasport yoki jonli suratda aniq ko'rinadigan yuz yo'q — yorug'likni yaxshilab qayta urinib ko'ring"
                  : "Jonli surat pasportdagi rasm bilan yetarlicha mos kelmadi. Yorug'likni yaxshilab, yuzni oval markaziga joylashtirib qayta urinib ko'ring"}
              </p>
              <Button size="sm" icon={RotateCcw} onClick={onRetake}>
                Qayta suratga olish
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
