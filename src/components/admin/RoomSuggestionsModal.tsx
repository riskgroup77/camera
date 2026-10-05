import { useEffect, useState } from 'react';
import { ArrowLeft, Check, Sparkles } from 'lucide-react';
import { api, ApiError } from '../../lib/apiClient';
import { Badge, Button, EmptyState, ErrorState, Modal, Skeleton, useToast } from '../../ui';

/**
 * Kamera qaysi xonada — dars jadvali va tanilgan odamlardan taklif
 * (camera-api/app/services/room_inference.py).
 *
 * Kamera dars vaqtida qaysi guruh talabalarini / qaysi o'qituvchini
 * tanigani HEMIS jadvali bilan solishtiriladi. Taklif avtomatik yozilmaydi:
 * admin "Qo'llash"ni bossa, xona raqami yoziladi va bugungi/kelajakdagi
 * darslar darhol shu kameraga bog'lanadi.
 */

export interface RoomSuggestion {
  cameraId: string;
  cameraName: string;
  currentRoom: string | null;
  currentBuilding: string | null;
  roomCode: string;
  buildingNumber: number;
  hemisBuilding: string | null;
  auditorium: string | null;
  buildingId: string | null;
  people: number;
  lessons: number;
  share: number;
  agrees: boolean;
  conflictCamera: string | null;
}

export default function RoomSuggestionsModal({ open, onClose, onApplied }: { open: boolean; onClose: () => void; onApplied: () => void }) {
  const toast = useToast();
  const [items, setItems] = useState<RoomSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setItems(null);
    setError(null);
    api
      .get<RoomSuggestion[]>('/api/xona-takliflari', undefined, { signal: controller.signal })
      .then(setItems)
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof ApiError ? err.message : "Takliflarni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [open, reload]);

  async function apply(item: RoomSuggestion) {
    setBusy(item.cameraId);
    try {
      const result = await api.post<{ message: string }>(`/api/xona-takliflari/${item.cameraId}/qollash`, {
        roomCode: item.roomCode,
        buildingId: item.buildingId,
      });
      toast.success(result.message);
      setItems((current) => (current ?? []).map((row) => (row.cameraId === item.cameraId ? { ...row, agrees: true } : row)));
      onApplied();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Qo'llab bo'lmadi");
    } finally {
      setBusy(null);
    }
  }

  const pending = (items ?? []).filter((item) => !item.agrees);

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="Xona takliflari"
      description="Kamera dars paytida kimni tanigani va HEMIS dars jadvali bo'yicha"
      footer={
        <Button icon={ArrowLeft} onClick={onClose}>
          Yopish
        </Button>
      }
    >
      {error ? (
        <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />
      ) : !items ? (
        <div className="space-y-2">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : pending.length === 0 ? (
        <EmptyState
          title="Yangi taklif yo'q"
          description="Takliflar kameralar dars paytida tanilgan talaba va o'qituvchilarni ko'rgan sari paydo bo'ladi"
          compact
        />
      ) : (
        <ul className="max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
          {pending.map((item) => (
            <li
              key={item.cameraId}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-control border border-border px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <b className="truncate text-[13px]">{item.cameraName}</b>
                  <span className="text-[12px] text-muted">→</span>
                  <span className="inline-flex items-center gap-1 text-[13px] font-semibold text-fg">
                    <Sparkles size={13} className="text-primary" aria-hidden="true" />
                    {item.auditorium ?? `${item.roomCode}-xona`}, {item.hemisBuilding ?? `${item.buildingNumber}-bino`}
                  </span>
                  {item.currentRoom && <Badge tone="warning">hozir: {item.currentRoom}</Badge>}
                </div>
                <p className="mt-0.5 text-[12px] text-muted">
                  {item.people} kishi, {item.lessons} ta darsda · ovozlarning {Math.round(item.share * 100)}%
                  {item.conflictCamera ? ` · diqqat: bu xona "${item.conflictCamera}" kamerasiga ham yozilgan` : ''}
                  {!item.buildingId ? ' · bino tizimda topilmadi — faqat xona raqami yoziladi' : ''}
                </p>
              </div>
              <Button size="sm" variant="primary" icon={Check} disabled={busy !== null} onClick={() => apply(item)}>
                Qo&apos;llash
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
