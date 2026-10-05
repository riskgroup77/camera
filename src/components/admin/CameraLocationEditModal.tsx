import { useEffect, useState, type FormEvent } from 'react';
import { MapPin } from 'lucide-react';
import { Notice } from '../settings/kit';
import { Button, Field, Input, Modal, Select } from '../../ui';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useBuildings } from '../../lib/useBuildings';
import { useCameraZones } from '../../lib/useCameraZones';
import { ROOM_TYPE_HINTS, ROOM_TYPE_OPTIONS } from '../../lib/cameraRoles';
import type { CameraConfig, Department, RoomType } from '../../types';

/** Oynaga kerak bo'ladigan minimal ma'lumot.
 *
 * Admin ro'yxatidagi `CameraConfig` ham, monitoring devoridagi
 * `CameraFeed` ham shu shaklga to'g'ri keladi — shuning uchun bitta oyna
 * ikkala joydan ham ochiladi va qoidalar bir joyda qoladi. */
export interface CameraLocationTarget {
  id: string;
  name: string;
  building: string;
  zone: string;
  floor?: number | null;
  /** Kafedra nomi; biriktirilmagan bo'lsa bo'sh. */
  department?: string;
  roomType?: RoomType | null;
  effectiveRoomType?: RoomType | null;
  roomCode?: string | null;
  faceDirection?: 'kirish' | 'chiqish' | null;
}

const FACE_DIRECTION_OPTIONS = [
  { value: 'kirish', label: 'Binoga kirayotganlarning' },
  { value: 'chiqish', label: 'Binodan chiqayotganlarning' },
];

/** Kameraning JOYLASHUVINI to'g'rilash: nomi, binosi, qavati, zonasi, kafedrasi.
 *
 * Nega alohida oyna: to'liq tahrirlash formasi IP, port, RTSP yo'li va
 * login/parolni ham yuboradi — bitta noto'g'ri yuborilgan maydon
 * kameraning ulanishini yo'qotadi. Bu yerda ulanish maydonlari umuman
 * yo'q va so'rovda ham yuborilmaydi (PATCH /api/cameras/{id}/location),
 * ya'ni ularga tasodifan tegib bo'lmaydi. */
export default function CameraLocationEditModal({
  camera,
  onClose,
  onSave,
}: {
  camera: CameraLocationTarget | null;
  onClose: () => void;
  onSave: (camera: CameraConfig) => void;
}) {
  const { token } = useAuth();
  const { buildings } = useBuildings();
  const [name, setName] = useState('');
  const [building, setBuilding] = useState('');
  const [floor, setFloor] = useState('');
  const [zone, setZone] = useState('');
  const [department, setDepartment] = useState('');
  const [roomType, setRoomType] = useState<RoomType | ''>('');
  const [roomCode, setRoomCode] = useState('');
  const [faceDirection, setFaceDirection] = useState<'kirish' | 'chiqish' | ''>('');
  const [departments, setDepartments] = useState<Department[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; zone?: string; floor?: string }>({});
  const { zones, reload: reloadZones } = useCameraZones(building || undefined);
  // Monitoring devoridagi kamera obyektida xona turi yo'q — u yerdan
  // ochilganda bu maydonlar ko'rsatilmaydi va YUBORILMAYDI (aks holda
  // saqlash admin belgilagan turni jimgina o'chirib yuborardi).
  const roomKnown = camera?.roomType !== undefined;

  useEffect(() => {
    if (!camera) return;
    setName(camera.name);
    setBuilding(camera.building);
    setFloor(camera.floor === null || camera.floor === undefined ? '' : String(camera.floor));
    setZone(camera.zone);
    setDepartment(camera.department ?? '');
    setRoomType(camera.roomType ?? '');
    setRoomCode(camera.roomCode ?? '');
    setFaceDirection(camera.faceDirection ?? '');
    setError(null);
    setFieldErrors({});
    // Oyna ochilganda zona (xona) ro'yxati qayta olinadi — boshqa joyda
    // qo'shilgan xona nomi shu yerda ham chiqsin.
    reloadZones();
  }, [camera, reloadZones]);

  useEffect(() => {
    if (!camera || !token) return;
    let cancelled = false;
    api
      .get<Department[]>('/api/departments', token)
      .then((rows) => {
        if (!cancelled) setDepartments(rows);
      })
      .catch(() => {
        /* ro'yxat kelmasa kafedra tanlovi bo'sh qoladi — joylashuv baribir saqlanadi */
      });
    return () => {
      cancelled = true;
    };
  }, [camera, token]);

  // Kafedra jismonan bitta binoda: tanlangan binoniki ko'rsatiladi, hozir
  // biriktirilgani esa (boshqa binoda bo'lsa ham) ro'yxatdan tushib qolmaydi.
  const departmentOptions = departments
    .filter((item) => !building || item.buildingName === building || item.name === department)
    .map((item) => ({ value: item.name, label: item.name }));

  // Joriy bino ro'yxatda bo'lmasa ham (eski/o'chirilgan) tanlovda ko'rinsin.
  const buildingOptions = buildings.map((item) => ({ value: item.name, label: item.name }));
  if (building && !buildingOptions.some((item) => item.value === building)) buildingOptions.unshift({ value: building, label: building });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!camera) return;
    // Forma `noValidate` bilan yuboriladi, ya'ni input'dagi min/max
    // brauzer tomonidan TEKSHIRILMAYDI: "2,5" yoki "999" yozilsa
    // Number(...) ni serverga jo'natardik (bo'sh bo'lmagan, lekin
    // raqamsiz qiymatda esa NaN → JSON'da null bo'lib ketardi).
    const floorValue = floor.trim() === '' ? null : Number(floor);
    const floorInvalid =
      floorValue !== null && (!Number.isInteger(floorValue) || floorValue < -5 || floorValue > 50);
    const nextErrors = {
      name: name.trim().length < 2 ? 'Kamera nomi kamida 2 belgi bo‘lishi kerak' : undefined,
      zone: !zone.trim() ? 'Zona (xona) nomini kiriting' : undefined,
      floor: floorInvalid ? "Qavat -5 dan 50 gacha butun son bo'lishi kerak" : undefined,
    };
    setFieldErrors(nextErrors);
    if (nextErrors.name || nextErrors.zone || nextErrors.floor) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.patch<CameraConfig>(
        `/api/cameras/${camera.id}/location`,
        {
          name: name.trim(),
          building: building || undefined,
          // Bo'sh maydon "qavat belgilanmagan" degani; buni None'dan
          // ("tegmaslik") ajratish uchun alohida bayroq bor.
          floor: floorValue,
          clearFloor: floor.trim() === '',
          zone: zone.trim(),
          department: department || undefined,
          clearDepartment: department === '',
          ...(roomKnown
            ? {
                roomType: roomType || undefined,
                clearRoomType: roomType === '',
                roomCode: roomCode.trim() || undefined,
                clearRoomCode: roomCode.trim() === '',
                faceDirection: faceDirection || undefined,
                clearFaceDirection: faceDirection === '',
              }
            : {}),
        },
        token,
      );
      onSave(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={!!camera}
      onClose={onClose}
      title="Kamera joylashuvi"
      description={camera?.name}
      size="md"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button type="submit" form="camera-location-form" variant="primary" icon={MapPin} loading={saving}>
            Saqlash
          </Button>
        </>
      }
    >
      <form id="camera-location-form" onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <Notice tone="neutral">
          Bu yerda faqat kameraning joylashuvi o&apos;zgaradi. Ulanish sozlamalari (IP, port, RTSP, login/parol) o&apos;z
          holicha qoladi — ular bu so&apos;rovda umuman yuborilmaydi.
        </Notice>

        <Field label="Kamera nomi" required error={fieldErrors.name}>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Masalan: 2-qavat kirish" />
        </Field>

        <Field label="Bino">
          <Select value={building} onChange={setBuilding} placeholder="Tanlang" options={buildingOptions} />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Qavat" hint="Bo'sh — qavat belgilanmagan" error={fieldErrors.floor}>
            <Input type="number" min={-5} max={50} placeholder="Belgilanmagan" value={floor} onChange={(event) => setFloor(event.target.value)} />
          </Field>
          <Field label="Zona (xona)" required error={fieldErrors.zone}>
            <Input value={zone} onChange={(event) => setZone(event.target.value)} placeholder="Masalan: 205-xona" list="camera-location-zones" />
          </Field>
          <datalist id="camera-location-zones">
            {zones.map((item) => (
              <option key={item.zone} value={item.zone}>
                {item.cameraCount} ta kamera
              </option>
            ))}
          </datalist>
        </div>

        <Field
          label="Kafedra"
          hint={departmentOptions.length === 0 ? "Bu binoda kafedra yo'q — «Tashkiliy tuzilma» sahifasida qo'shiladi." : undefined}
        >
          <Select value={department} onChange={setDepartment} placeholder="Kafedrasiz" options={departmentOptions} />
        </Field>

        {roomKnown && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Xona turi"
              hint={roomType ? ROOM_TYPE_HINTS[roomType] : 'Turi belgilanmagan kamerada faqat xavfsizlik mezonlari ishlaydi'}
            >
              <Select
                value={roomType}
                onChange={(value) => setRoomType(value as RoomType | '')}
                placeholder={camera?.effectiveRoomType && !roomType ? 'Belgilanmagan (bayroqdan: kirish/perimetr)' : 'Belgilanmagan'}
                options={ROOM_TYPE_OPTIONS}
              />
            </Field>
            <Field label="Xona raqami (dars jadvali)">
              <Input value={roomCode} onChange={(event) => setRoomCode(event.target.value)} placeholder="Masalan: 211" />
            </Field>
          </div>
        )}

        {roomKnown && (roomType || camera?.effectiveRoomType) === 'kirish' && (
          <Field
            label="Kamera kimning yuzini ko'radi"
            hint="Kelish va ketishni ajratadi"
          >
            <Select
              value={faceDirection}
              onChange={(value) => setFaceDirection(value as 'kirish' | 'chiqish' | '')}
              placeholder="Noma'lum (ikkala tomon)"
              options={FACE_DIRECTION_OPTIONS}
            />
          </Field>
        )}

        {error && <Notice tone="danger">{error}</Notice>}
      </form>
    </Modal>
  );
}
