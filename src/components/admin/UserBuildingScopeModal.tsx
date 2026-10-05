import { useEffect, useState } from 'react';
import { Button, Modal } from '../../ui';
import { Checkbox } from '../settings/kit';
import { api } from '../../lib/apiClient';
import { useBuildings } from '../../lib/useBuildings';
import type { AdminUser } from '../../types';

/**
 * Foydalanuvchi qaysi binolar kameralarini ko'rishi (bino doirasi).
 * Hech biri belgilanmasa — barcha binolar. Haqiqiy chegara serverda
 * (camera-api/app/services/access_scope.py); bu yerda faqat tanlash.
 */
export default function UserBuildingScopeModal({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUser;
  onClose: () => void;
  onSaved: (user: AdminUser) => void;
}) {
  const { buildings, loading } = useBuildings();
  const [selected, setSelected] = useState<Set<string>>(() => new Set(user.allowedBuildingIds ?? []));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setSelected(new Set(user.allowedBuildingIds ?? [])), [user]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.put<AdminUser>(`/api/users/${user.id}/binolar`, { buildingIds: [...selected] });
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Tarmoq xatosi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Bino doirasi"
      description={`${user.name} — faqat belgilangan binolar kameralari, hodisalari va arxivi ko‘rinadi.`}
      size="sm"
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button variant="primary" onClick={save} loading={saving}>
            Saqlash
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-2.5 text-[13px]">
        {error && (
          <p role="alert" className="rounded-control border border-danger/35 bg-danger-soft px-3 py-2 font-medium text-danger">
            {error}
          </p>
        )}
        <p className="text-muted">
          {selected.size === 0 ? 'Hech biri belgilanmagan — barcha binolar.' : `${selected.size} ta bino tanlangan.`}
        </p>
        {loading && <p className="text-muted">Yuklanmoqda…</p>}
        {!loading && buildings.length === 0 && <p className="text-muted">Binolar yo‘q.</p>}
        <div className="flex max-h-72 flex-col gap-2 overflow-y-auto pr-1">
          {buildings.map((b) => (
            <Checkbox key={b.id} label={b.name} checked={selected.has(b.id)} onChange={() => toggle(b.id)} />
          ))}
        </div>
        {selected.size > 0 && (
          <button type="button" className="self-start text-[12px] font-medium text-primary hover:underline" onClick={() => setSelected(new Set())}>
            Barchasini ko‘rsin
          </button>
        )}
      </div>
    </Modal>
  );
}
