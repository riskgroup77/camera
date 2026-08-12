import { useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, Loader2, Wifi, XCircle } from 'lucide-react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required, ipAddress, numberRange } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useBuildings } from '../../lib/useBuildings';
import { useCameraZones } from '../../lib/useCameraZones';
import type { CameraConfig } from '../../types';

interface FormState {
  name: string;
  ip: string;
  port: string;
  rtspPath: string;
  rtspUsername: string;
  rtspPassword: string;
  building: string;
  zone: string;
  resolution: string;
  fps: string;
  status: CameraConfig['status'];
}

function toForm(c?: CameraConfig | null): FormState {
  return {
    name: c?.name ?? '',
    ip: c?.ip ?? '',
    port: String(c?.port ?? 554),
    rtspPath: c?.rtspPath ?? '',
    // Kirim vaqtida hech qachon to'ldirilmaydi — backend rtsp login/parolni
    // hech qachon qaytarmaydi (haqiqiy sir). Bo'sh qoldirilsa PATCH mavjud
    // qiymatni o'zgartirmay saqlaydi (app/routers/cameras.py'ga qarang).
    rtspUsername: '',
    rtspPassword: '',
    building: c?.building ?? '',
    zone: c?.zone ?? '',
    resolution: c?.resolution ?? '1080p',
    fps: String(c?.fps ?? 25),
    status: c?.status ?? 'nofaol',
  };
}

interface ConnectionTestResult {
  success: boolean;
  message: string;
  latencyMs: number | null;
  videoInfo: string | null;
}

type TestState = 'idle' | 'testing' | 'success' | 'failed';

export default function AddCameraModal({
  open,
  camera,
  onClose,
  onSave,
}: {
  open: boolean;
  camera?: CameraConfig | null;
  onClose: () => void;
  onSave: (camera: CameraConfig) => void;
}) {
  const { token } = useAuth();
  const { buildings } = useBuildings();
  const isEdit = !!camera;
  const [form, setForm] = useState<FormState>(toForm(camera));
  const { zones } = useCameraZones(form.building || undefined);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>> & { form?: string }>({});
  const [testState, setTestState] = useState<TestState>('idle');
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(toForm(camera));
      setErrors({});
      setTestState('idle');
      setTestResult(null);
    }
  }, [open, camera]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setTestState('idle');
  }

  function validate(): boolean {
    const next: typeof errors = {
      name: required(form.name, 'Kamera nomi kiritilishi shart'),
      ip: required(form.ip, 'IP manzil kiritilishi shart') ?? ipAddress(form.ip),
      building: form.building ? undefined : 'Binoni tanlang',
      zone: required(form.zone, 'Zona nomi kiritilishi shart'),
      fps: numberRange(form.fps, 1, 60, "1 dan 60 gacha bo'lgan qiymat kiriting"),
      port: numberRange(form.port, 1, 65535, "1 dan 65535 gacha bo'lgan port kiriting"),
    };
    setErrors(next);
    return !Object.values(next).some(Boolean);
  }

  async function runConnectionTest() {
    if (!validate()) return;
    setTestState('testing');
    setTestResult(null);
    try {
      const result = await api.post<ConnectionTestResult>(
        '/api/cameras/test-connection',
        {
          ip: form.ip.trim(),
          port: Number(form.port),
          rtspPath: form.rtspPath.trim() || null,
          rtspUsername: form.rtspUsername.trim() || null,
          rtspPassword: form.rtspPassword || null,
        },
        token,
      );
      setTestResult(result);
      setTestState(result.success ? 'success' : 'failed');
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi",
        latencyMs: null,
        videoInfo: null,
      });
      setTestState('failed');
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!validate()) return;

    setSaving(true);
    setErrors((prev) => ({ ...prev, form: undefined }));
    try {
      const payload = {
        name: form.name.trim(),
        ip: form.ip.trim(),
        port: Number(form.port),
        rtspPath: form.rtspPath.trim() || null,
        rtspUsername: form.rtspUsername.trim() || null,
        rtspPassword: form.rtspPassword || null,
        building: form.building,
        zone: form.zone.trim(),
        resolution: form.resolution,
        fps: Number(form.fps),
        status: form.status,
      };
      const saved = isEdit
        ? await api.patch<CameraConfig>(`/api/cameras/${camera.id}`, payload, token)
        : await api.post<CameraConfig>('/api/cameras', payload, token);
      onSave(saved);
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSaving(false);
    }
  }

  const canSave = isEdit || testState === 'success';

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Kamerani sozlash' : "Yangi kamera qo'shish"}
      maxWidth="max-w-md"
    >
      <form onSubmit={handleSave} noValidate className="flex flex-col gap-4">
        {errors.form && (
          <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {errors.form}
          </p>
        )}
        <TextField
          label="Kamera nomi"
          placeholder="Kirish eshigi kamerasi"
          value={form.name}
          onChange={(e) => set('name', e.target.value)}
          error={errors.name}
        />
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="IP manzil"
            placeholder="192.168.1.101"
            value={form.ip}
            onChange={(e) => set('ip', e.target.value)}
            error={errors.ip}
          />
          <TextField
            label="RTSP port"
            type="number"
            min={1}
            max={65535}
            value={form.port}
            onChange={(e) => set('port', e.target.value)}
            error={errors.port}
          />
        </div>
        <TextField
          label="RTSP yo'l (ixtiyoriy)"
          placeholder="/stream1"
          value={form.rtspPath}
          onChange={(e) => set('rtspPath', e.target.value)}
        />
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="RTSP login (ixtiyoriy)"
            value={form.rtspUsername}
            onChange={(e) => set('rtspUsername', e.target.value)}
            autoComplete="off"
          />
          <TextField
            label="RTSP parol (ixtiyoriy)"
            type="password"
            value={form.rtspPassword}
            onChange={(e) => set('rtspPassword', e.target.value)}
            autoComplete="new-password"
          />
        </div>
        {isEdit && (
          <p className="-mt-2 text-[11px] text-slate-400 dark:text-slate-500">
            Login/parol bo'sh qoldirilsa, avval saqlangan qiymat o'zgarishsiz qoladi.
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Bino"
            placeholder="Tanlang"
            value={form.building}
            onChange={(e) => set('building', e.target.value)}
            error={errors.building}
            options={buildings.map((b) => ({ value: b.name, label: b.name }))}
          />
          <div>
            <TextField
              label="Zona"
              placeholder="A-Zona (Kirish)"
              value={form.zone}
              onChange={(e) => set('zone', e.target.value)}
              error={errors.zone}
              list="camera-zone-options"
            />
            <datalist id="camera-zone-options">
              {zones.map((z) => (
                <option key={z.zone} value={z.zone}>
                  {z.cameraCount} ta kamera
                </option>
              ))}
            </datalist>
            {(() => {
              const existing = zones.find((z) => z.zone === form.zone.trim());
              return existing ? (
                <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
                  Bu xonada allaqachon {existing.cameraCount} ta kamera bor — yangisi qo'shiladi
                </p>
              ) : null;
            })()}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Ruxsat"
            value={form.resolution}
            onChange={(e) => set('resolution', e.target.value)}
            options={[
              { value: '720p', label: '720p' },
              { value: '1080p', label: '1080p' },
              { value: '4K', label: '4K' },
            ]}
          />
          <TextField
            label="FPS"
            type="number"
            min={1}
            max={60}
            value={form.fps}
            onChange={(e) => set('fps', e.target.value)}
            error={errors.fps}
          />
        </div>
        <SelectField
          label="Holat"
          value={form.status}
          onChange={(e) => set('status', e.target.value as CameraConfig['status'])}
          options={[
            { value: 'faol', label: 'Faol' },
            { value: 'nofaol', label: 'Nofaol' },
            { value: 'tamirda', label: "Ta'mirda" },
          ]}
        />

        {!isEdit && (
          <div>
            <button
              type="button"
              onClick={runConnectionTest}
              disabled={testState === 'testing'}
              className="btn-glass flex w-full items-center justify-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {testState === 'testing' ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Wifi size={14} />
              )}
              {testState === 'testing' ? 'Ulanish tekshirilmoqda...' : 'Ulanishni tekshirish'}
            </button>

            {testState === 'success' && testResult && (
              <p className="mt-2 flex items-center gap-1.5 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={14} />
                {testResult.message}
                {testResult.latencyMs != null ? ` (${testResult.latencyMs} ms)` : ''}
              </p>
            )}
            {testState === 'failed' && testResult && (
              <p className="mt-2 flex items-center gap-1.5 rounded-xl bg-red-50 dark:bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-600 dark:text-red-400">
                <XCircle size={14} />
                {testResult.message}
              </p>
            )}
            <p className="mt-1.5 text-[11px] text-slate-400 dark:text-slate-500">
              Haqiqiy tekshiruv: TCP portga ulanish va imkon bo'lsa RTSP oqimini ffprobe orqali tasdiqlash.
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-glass">
            Bekor qilish
          </button>
          <button
            type="submit"
            disabled={!canSave || saving}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? 'Saqlanmoqda...' : 'Saqlash'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
