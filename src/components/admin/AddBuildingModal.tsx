import { useEffect, useId, useState, type FormEvent } from 'react';
import { Button, ErrorState, Field, Input, Modal } from '../../ui';
import { required, minLength, numberRange } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Building } from '../../types';

export default function AddBuildingModal({
  open,
  building,
  onClose,
  onSave,
}: {
  open: boolean;
  building?: Building | null;
  onClose: () => void;
  onSave: (building: Building) => void;
}) {
  const { token } = useAuth();
  const formId = useId();
  const isEdit = !!building;
  const [name, setName] = useState(building?.name ?? '');
  const [floors, setFloors] = useState(building?.floors ? String(building.floors) : '');
  const [nameError, setNameError] = useState<string>();
  const [floorsError, setFloorsError] = useState<string>();
  const [formError, setFormError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setName(building?.name ?? '');
      setFloors(building?.floors ? String(building.floors) : '');
      setNameError(undefined);
      setFloorsError(undefined);
      setFormError(undefined);
    }
  }, [open, building]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const err = required(name, 'Bino nomi kiritilishi shart') ?? minLength(name, 3);
    // Qavatlar soni ixtiyoriy, lekin kiritilsa haqiqiy bo'lishi kerak:
    // ilgari 0, −3 yoki 900 ham serverga ketardi va monitoringdagi bino
    // kesimi o'sha raqam bo'yicha chizilib buzilardi.
    const floorsErr = floors.trim() === '' ? undefined : numberRange(floors, 1, 50, "Qavatlar soni 1 dan 50 gacha bo'lishi kerak");
    setNameError(err);
    setFloorsError(floorsErr);
    if (err || floorsErr) return;

    setSubmitting(true);
    setFormError(undefined);
    try {
      const payload = {
        name: name.trim(),
        cameraCount: building?.cameraCount ?? 0,
        // Bo'sh qoldirilsa qavatlar soni noma'lum bo'lib qoladi: monitoring
        // kesimi u holda faqat kameralari bor qavatlarni chizadi.
        floors: floors.trim() === '' ? null : Number(floors),
      };
      const saved = isEdit
        ? await api.patch<Building>(`/api/buildings/${building.id}`, payload, token)
        : await api.post<Building>('/api/buildings', payload, token);
      onSave(saved);
      onClose();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      dismissible={!submitting}
      title={isEdit ? 'Korpusni tahrirlash' : "Yangi korpus qo'shish"}
      footer={
        <>
          <Button onClick={onClose} disabled={submitting}>
            Bekor qilish
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={submitting}>
            {isEdit ? 'Saqlash' : "Qo'shish"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {formError && <ErrorState title="Saqlab bo'lmadi" message={formError} />}
        <Field label="Bino nomi" required error={nameError}>
          <Input placeholder="4-Bino (Sport majmuasi)" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field
          label="Qavatlar soni"
          error={floorsError}
          hint="Bino kesimi shuncha qavat chizadi"
        >
          <Input type="number" min={1} max={50} placeholder="Masalan: 4" value={floors} onChange={(e) => setFloors(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}
