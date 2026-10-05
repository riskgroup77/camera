import { useEffect, useState } from 'react';
import { Ban, RotateCcw, Trash2, VideoOff } from 'lucide-react';
import LiveVideoPlayer from '../LiveVideoPlayer';
import { Notice } from '../settings/kit';
import { Button, Modal } from '../../ui';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { appendPoint, validatePolygon } from './zonePolygon';
import type { CameraConfig } from '../../types';

/** Taqiqlangan zona chizish oynasi (TT kriteriya 2) — jonli video ustiga
 * bosib ko'pburchak nuqtalarini belgilaydi, xuddi
 * FaceDetectionOverlay/computeBoxes'dagi object-cover koordinata
 * matematikasidan foydalanib (bu safar teskari yo'nalishda,
 * ZoneOverlay.tsx'ga qarang). Kamida 3 ta nuqta kerak — kamroq bo'lsa
 * backend (app/routers/cameras.py) 422 bilan rad etadi.
 *
 * `mode="faceRoi"` — xuddi shu oyna kirish kamerasining ESHIK HUDUDINI
 * chizadi (Camera.faceRoi): AI yuzni faqat shu hududda, to'liq sifatda
 * qidiradi — kadrning qolgan qismi tahlil qilinmaydi. */
type ZoneMode = 'restricted' | 'faceRoi';

const MODE_TEXT: Record<ZoneMode, { title: string; endpoint: string; hint: string; clear: string }> = {
  restricted: {
    title: 'Taqiqlangan zona',
    endpoint: 'zone-polygon',
    hint: 'Video ustiga bosib nuqta qo‘ying (kamida 3 ta).',
    clear: 'Zonani olib tashlash',
  },
  faceRoi: {
    title: 'Eshik hududi (yuz qidiriladigan joy)',
    endpoint: 'face-roi',
    hint: 'Eshik atrofini belgilang (kamida 3 ta nuqta).',
    clear: 'Hududni olib tashlash',
  },
};

export default function CameraZoneModal({
  open,
  camera,
  onClose,
  onSave,
  mode = 'restricted',
}: {
  open: boolean;
  camera: CameraConfig | null;
  onClose: () => void;
  onSave: (camera: CameraConfig) => void;
  mode?: ZoneMode;
}) {
  const text = MODE_TEXT[mode];
  const { token } = useAuth();
  const [points, setPoints] = useState<[number, number][]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Serverdagi joriy holat. `camera` prop oyna ochiq turganda
   *  YANGILANMAYDI, shuning uchun ilgari "olib tashlash"dan keyin ham
   *  o'sha tugma turaverardi va "zona bor" deb ko'rsatardi. */
  const [savedPoints, setSavedPoints] = useState<[number, number][]>([]);
  /** Xavfli amallarni tasdiqlash: 'clear' — mavjud zonani o'chirish,
   *  'discard' — saqlanmagan o'zgarishlar bilan chiqib ketish. */
  const [confirming, setConfirming] = useState<null | 'clear' | 'discard'>(null);

  useEffect(() => {
    if (open) {
      const current = (mode === 'faceRoi' ? camera?.faceRoi : camera?.restrictedZonePolygon) ?? [];
      setPoints(current);
      setSavedPoints(current);
      setError(null);
      setConfirming(null);
    }
  }, [open, camera, mode]);

  const dirty = JSON.stringify(points) !== JSON.stringify(savedPoints);

  async function submit(polygon: [number, number][] | null) {
    if (!camera) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.patch<CameraConfig>(
        `/api/cameras/${camera.id}/${text.endpoint}`,
        { polygon },
        token,
      );
      const next = polygon ?? [];
      setPoints(next);
      setSavedPoints(next);
      setConfirming(null);
      onSave(saved);
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    // Barcha nuqtalarni o'chirib "Saqlash" bosilsa, bu mavjud zonani
    // O'CHIRISH degani — buni tasodifan qilib qo'ymasin.
    if (points.length === 0 && savedPoints.length > 0) {
      setConfirming('clear');
      return;
    }
    const problem = validatePolygon(points);
    if (problem) {
      setError(problem);
      return;
    }
    if (await submit(points.length > 0 ? points : null)) onClose();
  }

  /** Saqlanmagan nuqtalar bilan yopishda ogohlantiramiz — ilgari chizilgan
   *  zona jimgina yo'qolardi (Escape bosilsa ham). */
  function handleClose() {
    if (saving) return;
    if (dirty) {
      setConfirming('discard');
      return;
    }
    onClose();
  }

  const hasStream = !!camera?.streamUrl && camera.status === 'faol';

  return (
    <Modal
      open={open && !!camera}
      onClose={handleClose}
      title={text.title}
      description={camera?.name}
      size="lg"
      dismissible={!saving}
      footer={
        <>
          {savedPoints.length > 0 && (
            <Button
              variant="ghost"
              icon={Ban}
              onClick={() => setConfirming('clear')}
              disabled={saving}
              className="mr-auto text-danger hover:bg-danger-soft hover:text-danger"
            >
              {text.clear}
            </Button>
          )}
          <Button onClick={handleClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button variant="primary" onClick={handleSave} loading={saving} disabled={!dirty}>
            Saqlash
          </Button>
        </>
      }
    >
      {camera && (
        <div className="flex flex-col gap-4">
          {/* Video maydoni mavzudan qat'i nazar qora — kadr shunday ko'rinadi. */}
          <div className="relative flex aspect-video items-center justify-center overflow-hidden border border-border-strong bg-black">
            {hasStream ? (
              <LiveVideoPlayer
                streamUrl={camera.streamUrl}
                /* Zona chizish uchun tasvir DARHOL kerak — umumiy HLS
                   navbatida kutib turmaydi (streamLoadQueue izohiga qarang). */
                priority
                zoneEditing
                zonePoints={points}
                onZonePointAdd={(p) => setPoints((prev) => appendPoint(prev, p))}
              />
            ) : (
              <div className="flex max-w-sm flex-col items-center gap-1.5 px-4 text-center text-subtle">
                <VideoOff size={20} aria-hidden="true" />
                <span className="text-xs font-medium">
                  Video oqim mavjud emas — zona chizish uchun kamera faol va oqim ulangan bo&apos;lishi kerak
                </span>
              </div>
            )}
          </div>

          {hasStream && <p className="text-[13px] text-muted">{text.hint}</p>}

          {error && <Notice tone="danger">{error}</Notice>}

          {confirming === 'clear' && (
            <Notice tone="warning" title={`${text.clear}?`}>
              <p>Saqlangan hudud butunlay o&apos;chiriladi.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" variant="primary" loading={saving} onClick={() => submit(null)}>
                  Ha, olib tashlansin
                </Button>
                <Button size="sm" onClick={() => setConfirming(null)} disabled={saving}>
                  Bekor qilish
                </Button>
              </div>
            </Notice>
          )}

          {confirming === 'discard' && (
            <Notice tone="warning" title="Saqlanmagan o'zgarishlar bor">
              <p>Oyna yopilsa, hozir belgilangan nuqtalar yo&apos;qoladi.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" onClick={onClose}>
                  Saqlamay chiqish
                </Button>
                <Button size="sm" variant="primary" onClick={() => setConfirming(null)}>
                  Chizishda qolish
                </Button>
              </div>
            </Notice>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[13px] text-muted">
              <span className="font-medium tabular-nums text-fg">{points.length}</span> ta nuqta belgilandi
            </span>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" icon={RotateCcw} disabled={points.length === 0} onClick={() => setPoints((prev) => prev.slice(0, -1))}>
                Oxirgisini bekor qilish
              </Button>
              <Button size="sm" icon={Trash2} disabled={points.length === 0} onClick={() => setPoints([])}>
                Tozalash
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
