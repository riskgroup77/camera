import { useEffect, useState, type FormEvent } from 'react';
import { Gamepad2, Wifi } from 'lucide-react';
import { forgetPtzAvailability } from '../ptz/usePtzAvailability';
import { Checkbox, Notice } from '../settings/kit';
import { Button, Field, Input, Modal, Select } from '../../ui';
import { required, ipAddress, numberRange } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { ptzApi, type PtzProbeResult } from '../../lib/ptzApi';
import { useBuildings } from '../../lib/useBuildings';
import { useCameraZones } from '../../lib/useCameraZones';
import type { CameraConfig, PtzProtocol } from '../../types';

interface FormState {
  name: string;
  ip: string;
  port: string;
  rtspPath: string;
  rtspUsername: string;
  rtspPassword: string;
  building: string;
  zone: string;
  floor: string;
  resolution: string;
  fps: string;
  status: CameraConfig['status'];
  isEntrance: boolean;
  isPerimeter: boolean;
  isExit: boolean;
  ptzEnabled: boolean;
  ptzProtocol: PtzProtocol | '';
  onvifPort: string;
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
    floor: c?.floor === null || c?.floor === undefined ? '' : String(c.floor),
    resolution: c?.resolution ?? '1080p',
    fps: String(c?.fps ?? 25),
    status: c?.status ?? 'nofaol',
    isEntrance: c?.isEntrance ?? false,
    isPerimeter: c?.isPerimeter ?? false,
    isExit: c?.isExit ?? false,
    ptzEnabled: c?.ptzEnabled ?? false,
    ptzProtocol: c?.ptzProtocol ?? '',
    onvifPort: c?.onvifPort ? String(c.onvifPort) : '',
  };
}

type PtzProbeState = 'idle' | 'testing' | 'done';

interface ConnectionTestResult {
  success: boolean;
  message: string;
  latencyMs: number | null;
  videoInfo: string | null;
}

type TestState = 'idle' | 'testing' | 'success' | 'failed';

const RESOLUTION_OPTIONS = [
  { value: '720p', label: '720p' },
  { value: '1080p', label: '1080p' },
  { value: '4K', label: '4K' },
];

const STATUS_OPTIONS = [
  { value: 'faol', label: 'Faol' },
  { value: 'nofaol', label: 'Nofaol' },
  { value: 'tamirda', label: "Ta'mirda" },
];

const PTZ_PROTOCOL_OPTIONS = [
  { value: 'onvif', label: 'ONVIF' },
  { value: 'isapi', label: 'Hikvision ISAPI' },
];

const PTZ_KEYS: Array<keyof FormState> = ['ptzEnabled', 'ptzProtocol', 'onvifPort'];

function SubHeading({ children }: { children: string }) {
  return <h3 className="intel-micro intel-micro-wrap !text-fg border-b border-border pb-1">{children}</h3>;
}

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
  const { zones, reload: reloadZones } = useCameraZones(form.building || undefined);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>> & { form?: string }>({});
  const [testState, setTestState] = useState<TestState>('idle');
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [ptzProbeState, setPtzProbeState] = useState<PtzProbeState>('idle');
  const [ptzProbe, setPtzProbe] = useState<PtzProbeResult | null>(null);

  useEffect(() => {
    if (open) {
      setForm(toForm(camera));
      setErrors({});
      setTestState('idle');
      setTestResult(null);
      setPtzProbeState('idle');
      setPtzProbe(null);
      // Oyna oxirgi ochilgandan beri zona (xona) ro'yxati o'zgargan
      // bo'lishi mumkin — avtoto'ldirish eskirmasin.
      reloadZones();
    }
  }, [open, camera, reloadZones]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    // PTZ maydonlari RTSP ulanishiga ta'sir qilmaydi — ulanish tekshiruvini
    // qayta talab qilmaymiz.
    if (!PTZ_KEYS.includes(key)) setTestState('idle');
    if (key === 'ip' || key === 'onvifPort' || key === 'ptzProtocol' || key === 'rtspUsername' || key === 'rtspPassword') {
      setPtzProbeState('idle');
      setPtzProbe(null);
    }
  }

  /** PTZ ulanishini tekshirish. Saqlangan kamerada login/parol bazadan
   * olinadi (formada yangisi yozilgan bo'lsa — o'sha); yangi kamerada —
   * formadan. Protokol tanlanmagan bo'lsa backend ONVIF, keyin ISAPI'ni
   * sinab ko'radi va ishlaganini qaytaradi. */
  async function runPtzProbe() {
    const ipError = required(form.ip, 'IP manzil kiritilishi shart') ?? ipAddress(form.ip);
    const portError =
      form.onvifPort.trim() === '' ? undefined : numberRange(form.onvifPort, 1, 65535, '1–65535');
    if (ipError || portError) {
      setErrors((prev) => ({ ...prev, ip: ipError, onvifPort: portError }));
      return;
    }
    setPtzProbeState('testing');
    setPtzProbe(null);
    const overrides = {
      protocol: form.ptzProtocol || null,
      onvifPort: form.onvifPort.trim() ? Number(form.onvifPort) : null,
      username: form.rtspUsername.trim() || null,
      password: form.rtspPassword || null,
    };
    try {
      const result = isEdit
        ? await ptzApi.probe(camera.id, overrides)
        : await ptzApi.probeUnsaved({ ip: form.ip.trim(), ...overrides });
      setPtzProbe(result);
      if (result.success && result.protocol) {
        setForm((f) => ({ ...f, ptzProtocol: result.protocol ?? f.ptzProtocol }));
        setErrors((prev) => ({ ...prev, ptzProtocol: undefined }));
      }
    } catch (err) {
      setPtzProbe({
        success: false,
        message: err instanceof ApiError ? err.message : 'Tarmoq xatosi',
        protocol: null,
        reachable: false,
        authenticated: false,
        ptzSupported: false,
        presetsSupported: false,
        presetCount: null,
        deviceInfo: null,
        latencyMs: null,
        tried: [],
      });
    } finally {
      setPtzProbeState('done');
    }
  }

  function validate(): boolean {
    const next: typeof errors = {
      name: required(form.name, 'Kamera nomi kiritilishi shart'),
      ip: required(form.ip, 'IP manzil kiritilishi shart') ?? ipAddress(form.ip),
      building: form.building ? undefined : 'Binoni tanlang',
      zone: required(form.zone, 'Zona nomi kiritilishi shart'),
      fps: numberRange(form.fps, 1, 60, "1 dan 60 gacha bo'lgan qiymat kiriting"),
      floor: form.floor.trim() === '' ? undefined : numberRange(form.floor, -5, 50, '-5 dan 50 gacha'),
      port: numberRange(form.port, 1, 65535, "1 dan 65535 gacha bo'lgan port kiriting"),
      onvifPort: form.onvifPort.trim() === '' ? undefined : numberRange(form.onvifPort, 1, 65535, '1–65535'),
      ptzProtocol:
        form.ptzEnabled && !form.ptzProtocol ? 'Protokolni tanlang' : undefined,
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
        message: err instanceof ApiError ? err.message : 'Tarmoq xatosi',
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
        // Bo'sh maydon = "qavat belgilanmagan" (null), 0 emas.
        floor: form.floor.trim() === '' ? null : Number(form.floor),
        resolution: form.resolution,
        fps: Number(form.fps),
        status: form.status,
        isEntrance: form.isEntrance,
        isPerimeter: form.isPerimeter,
        isExit: form.isExit,
        ptzEnabled: form.ptzEnabled,
        ptzProtocol: form.ptzProtocol || null,
        onvifPort: form.onvifPort.trim() ? Number(form.onvifPort) : null,
      };
      const saved = isEdit
        ? await api.patch<CameraConfig>(`/api/cameras/${camera.id}`, payload, token)
        : await api.post<CameraConfig>('/api/cameras', payload, token);
      forgetPtzAvailability(saved.id);
      onSave(saved);
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Tarmoq xatosi' });
    } finally {
      setSaving(false);
    }
  }

  const canSave = isEdit || testState === 'success';
  const existingZone = zones.find((z) => z.zone === form.zone.trim());

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Kamerani sozlash' : "Yangi kamera qo'shish"}
      description={isEdit ? camera?.name : 'Saqlashdan oldin ulanishni tekshiring.'}
      size="lg"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button
            type="submit"
            form="camera-form"
            variant="primary"
            loading={saving}
            disabled={!canSave}
            title={canSave ? undefined : 'Avval ulanishni tekshiring'}
          >
            Saqlash
          </Button>
        </>
      }
    >
      <form id="camera-form" onSubmit={handleSave} noValidate className="flex flex-col gap-5">
        {errors.form && <Notice tone="danger">{errors.form}</Notice>}

        <section className="flex flex-col gap-4">
          <SubHeading>Ulanish</SubHeading>
          <Field label="Kamera nomi" required error={errors.name}>
            <Input placeholder="Kirish eshigi kamerasi" value={form.name} onChange={(e) => set('name', e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-[1fr_9rem]">
            <Field label="IP manzil" required error={errors.ip}>
              <Input placeholder="192.168.1.101" className="font-mono" value={form.ip} onChange={(e) => set('ip', e.target.value)} />
            </Field>
            <Field label="RTSP port" error={errors.port}>
              <Input type="number" min={1} max={65535} value={form.port} onChange={(e) => set('port', e.target.value)} />
            </Field>
          </div>
          <Field label="RTSP yo'l" hint="Ixtiyoriy">
            <Input placeholder="/stream1" className="font-mono" value={form.rtspPath} onChange={(e) => set('rtspPath', e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="RTSP login" hint={isEdit ? "Bo'sh — o'zgarmaydi" : 'Ixtiyoriy'}>
              <Input value={form.rtspUsername} onChange={(e) => set('rtspUsername', e.target.value)} autoComplete="off" />
            </Field>
            <Field label="RTSP parol" hint={isEdit ? "Bo'sh — o'zgarmaydi" : 'Ixtiyoriy'}>
              <Input type="password" value={form.rtspPassword} onChange={(e) => set('rtspPassword', e.target.value)} autoComplete="new-password" />
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-4">
          <SubHeading>Joylashuv</SubHeading>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Bino" required error={errors.building}>
              <Select
                value={form.building}
                onChange={(value) => set('building', value)}
                placeholder="Tanlang"
                options={buildings.map((b) => ({ value: b.name, label: b.name }))}
               
              />
            </Field>
            <Field
              label="Zona"
              required
              error={errors.zone}
              hint={existingZone ? `Bu xonada allaqachon ${existingZone.cameraCount} ta kamera bor — yangisi qo'shiladi` : undefined}
            >
              <Input placeholder="A-Zona (Kirish)" value={form.zone} onChange={(e) => set('zone', e.target.value)} list="camera-zone-options" />
            </Field>
            <datalist id="camera-zone-options">
              {zones.map((z) => (
                <option key={z.zone} value={z.zone}>
                  {z.cameraCount} ta kamera
                </option>
              ))}
            </datalist>
          </div>
          <Field
            label="Qavat"
            error={errors.floor}
            hint="Bo'sh — «Qavat belgilanmagan»"
          >
            <Input type="number" min={-5} max={50} placeholder="Masalan: 3" value={form.floor} onChange={(e) => set('floor', e.target.value)} className="sm:max-w-[12rem]" />
          </Field>
        </section>

        <section className="flex flex-col gap-4">
          <SubHeading>Video va holat</SubHeading>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Ruxsat">
              <Select value={form.resolution} onChange={(value) => set('resolution', value)} options={RESOLUTION_OPTIONS} />
            </Field>
            <Field label="FPS" error={errors.fps}>
              <Input type="number" min={1} max={60} value={form.fps} onChange={(e) => set('fps', e.target.value)} />
            </Field>
            <Field label="Holat">
              <Select
                value={form.status}
                onChange={(value) => set('status', value as CameraConfig['status'])}
                options={STATUS_OPTIONS}
               
              />
            </Field>
          </div>
        </section>

        <fieldset className="flex flex-col gap-3">
          <legend className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-muted">Kamera roli</legend>
          <Checkbox
            checked={form.isEntrance}
            onChange={(e) => set('isEntrance', e.target.checked)}
            label="Kirish/koridor kamerasi"
            description="Bir necha kadr tekshiriladi."
          />
          <Checkbox
            checked={form.isPerimeter}
            onChange={(e) => set('isPerimeter', e.target.checked)}
            label="Hovli / perimetr kamerasi"
            description="Transport AI faqat shu kameralarda."
          />
          <Checkbox
            checked={form.isExit}
            onChange={(e) => set('isExit', e.target.checked)}
            label="Chiqish kamerasi"
            description="Faqat shu kamerada «ketdi» belgilanadi."
          />
        </fieldset>

        <fieldset className="flex flex-col gap-3 border border-border bg-surface-2 px-3 py-2.5">
          <legend className="sr-only">PTZ boshqaruvi</legend>
          <Checkbox
            checked={form.ptzEnabled}
            onChange={(e) => set('ptzEnabled', e.target.checked)}
            label={
              <span className="inline-flex items-center gap-1.5">
                <Gamepad2 size={15} className="text-primary" aria-hidden="true" />
                PTZ (buriladigan) kamera
              </span>
            }
            description="Operator uni monitoringdan boshqaradi."
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="PTZ protokoli" error={errors.ptzProtocol}>
              <Select
                value={form.ptzProtocol}
                onChange={(value) => set('ptzProtocol', value as FormState['ptzProtocol'])}
                placeholder="Aniqlanmagan"
                options={PTZ_PROTOCOL_OPTIONS}
               
              />
            </Field>
            <Field label="HTTP (ONVIF) port" error={errors.onvifPort}>
              <Input type="number" min={1} max={65535} placeholder="80" value={form.onvifPort} onChange={(e) => set('onvifPort', e.target.value)} />
            </Field>
          </div>
          <div className="flex flex-col gap-2">
            <Button icon={Gamepad2} onClick={runPtzProbe} loading={ptzProbeState === 'testing'} fullWidth>
              {ptzProbeState === 'testing' ? 'PTZ tekshirilmoqda…' : 'PTZ ni tekshirish'}
            </Button>
            {ptzProbe && (
              <Notice
                tone={ptzProbe.success ? 'success' : 'danger'}
                title={`${ptzProbe.message}${ptzProbe.latencyMs != null ? ` (${ptzProbe.latencyMs} ms)` : ''}`}
                action={
                  ptzProbe.success && !form.ptzEnabled ? (
                    <Button size="sm" variant="primary" onClick={() => set('ptzEnabled', true)}>
                      PTZ boshqaruvini yoqish
                    </Button>
                  ) : undefined
                }
              >
                {(ptzProbe.deviceInfo || (ptzProbe.success && !ptzProbe.presetsSupported)) && (
                  <>
                    {ptzProbe.deviceInfo && <p>Qurilma: {ptzProbe.deviceInfo}</p>}
                    {ptzProbe.success && !ptzProbe.presetsSupported && <p>Presetlar qo&apos;llab-quvvatlanmaydi</p>}
                  </>
                )}
              </Notice>
            )}
            <p className="text-xs text-muted">
              Login/parol — RTSP bilan bir xil. Protokol tanlanmasa, avval ONVIF, keyin Hikvision ISAPI sinaladi.
            </p>
          </div>
        </fieldset>

        {!isEdit && (
          <div className="flex flex-col gap-2">
            <Button icon={Wifi} onClick={runConnectionTest} loading={testState === 'testing'} fullWidth>
              {testState === 'testing' ? 'Ulanish tekshirilmoqda…' : 'Ulanishni tekshirish'}
            </Button>
            {testState === 'success' && testResult && (
              <Notice tone="success">
                {testResult.message}
                {testResult.latencyMs != null ? ` (${testResult.latencyMs} ms)` : ''}
              </Notice>
            )}
            {testState === 'failed' && testResult && <Notice tone="danger">{testResult.message}</Notice>}
            <p className="text-xs text-muted">
              Haqiqiy tekshiruv: TCP portga ulanish va imkon bo&apos;lsa RTSP oqimini ffprobe orqali tasdiqlash. Saqlash
              faqat muvaffaqiyatli tekshiruvdan keyin ochiladi.
            </p>
          </div>
        )}
      </form>
    </Modal>
  );
}
