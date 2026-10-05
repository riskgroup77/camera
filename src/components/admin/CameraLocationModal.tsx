import { useEffect, useState, type FormEvent } from 'react';
import { MapPin } from 'lucide-react';
import { Checkbox, Notice } from '../settings/kit';
import { Button, Field, Input, Modal, Select } from '../../ui';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useBuildings } from '../../lib/useBuildings';

/** Belgilangan kameralarga bino/qavat/zonani birdan qo'yish.
 *
 * Nega kerak: monitoring markazi kesimi kameraning qavatini bilishi
 * kerak, 107 ta kameraga esa uni bittalab kiritish real ish emas.
 * Bo'sh qoldirilgan maydon O'ZGARTIRILMAYDI — masalan faqat qavatni
 * qo'yish uchun binoni qayta tanlash shart emas. */
export default function CameraLocationModal({
  open,
  cameraIds,
  onClose,
  onSaved,
}: {
  open: boolean;
  cameraIds: string[];
  onClose: () => void;
  onSaved: (updated: number, notFound: number) => void;
}) {
  const { token } = useAuth();
  const { buildings } = useBuildings();
  const [building, setBuilding] = useState('');
  const [floor, setFloor] = useState('');
  const [zone, setZone] = useState('');
  const [clearFloor, setClearFloor] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setBuilding('');
    setFloor('');
    setZone('');
    setClearFloor(false);
    setError(null);
  }, [open]);

  const nothingToDo = !building && !zone && !clearFloor && floor.trim() === '';

  async function handleSave(event?: FormEvent) {
    event?.preventDefault();
    if (nothingToDo) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.post<{ updated: number; notFound: string[] }>(
        '/api/cameras/bulk-location',
        {
          cameraIds,
          building: building || null,
          floor: clearFloor || floor.trim() === '' ? null : Number(floor),
          clearFloor,
          zone: zone.trim() || null,
        },
        token,
      );
      // Server topa olmagan kameralar (boshqa operator o'chirgan bo'lishi
      // mumkin) jimgina yutilardi: "12 ta yangilandi" deyilardi-yu, aslida
      // 10 tasi yangilangan bo'lardi. Endi soni chaqiruvchiga uzatiladi.
      onSaved(res.updated, res.notFound.length);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Joylashuvni belgilash"
      description={`${cameraIds.length} ta tanlangan kamera`}
      size="md"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button type="submit" form="camera-bulk-location-form" variant="primary" icon={MapPin} loading={saving} disabled={nothingToDo}>
            Saqlash
          </Button>
        </>
      }
    >
      <form id="camera-bulk-location-form" onSubmit={handleSave} noValidate className="flex flex-col gap-4">
        <Notice tone="neutral">
          Bo&apos;sh qoldirilgan maydon o&apos;zgarmaydi. Qavat monitoring markazidagi bino kesimi uchun ishlatiladi:
          qavati belgilanmagan kameralar «Qavat belgilanmagan» guruhida to&apos;planadi.
        </Notice>

        <Field label="Bino">
          <Select value={building} onChange={setBuilding} placeholder="O'zgartirilmasin" options={buildings.map((b) => ({ value: b.name, label: b.name }))} />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Qavat">
            <Input
              type="number"
              min={-5}
              max={50}
              placeholder="O'zgartirilmasin"
              value={floor}
              onChange={(e) => {
                setFloor(e.target.value);
                if (e.target.value) setClearFloor(false);
              }}
              disabled={clearFloor}
            />
          </Field>
          <Field label="Zona (xona nomi)">
            <Input placeholder="O'zgartirilmasin" value={zone} onChange={(e) => setZone(e.target.value)} />
          </Field>
        </div>

        <Checkbox
          checked={clearFloor}
          onChange={(e) => {
            setClearFloor(e.target.checked);
            if (e.target.checked) setFloor('');
          }}
          label="Qavat belgisini olib tashlash"
          description="«Qavat belgilanmagan» guruhiga o'tadi."
        />

        {error && <Notice tone="danger">{error}</Notice>}
      </form>
    </Modal>
  );
}
