import { useState } from 'react';
import { CheckCheck, Download, ScanSearch } from 'lucide-react';
import { CsvDropzone } from './CameraImportModal';
import { Notice } from '../settings/kit';
import { Button, Modal } from '../../ui';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { downloadBlob } from '../../lib/download';
import { ROOM_TYPE_LABELS } from '../../lib/cameraRoles';
import type { RoomType } from '../../types';

interface RoleChange {
  cameraId: string;
  cameraName: string;
  field: 'room_type' | 'room_code' | 'face_direction';
  old: string | null;
  new: string | null;
}

interface RolesImportResult {
  rows: number;
  changes: RoleChange[];
  errors: { row: number; message: string }[];
  applied: boolean;
}

const FIELD_LABELS: Record<RoleChange['field'], string> = {
  room_type: 'tur',
  room_code: 'xona',
  face_direction: 'yuz yo‘nalishi',
};

const DIRECTION_LABELS: Record<string, string> = { kirish: 'kirayotganlar', chiqish: 'chiqayotganlar' };

function show(field: RoleChange['field'], value: string | null): string {
  if (value === null) return 'belgilanmagan';
  if (field === 'room_type') return ROOM_TYPE_LABELS[value as RoomType] ?? value;
  if (field === 'face_direction') return DIRECTION_LABELS[value] ?? value;
  return value;
}

/**
 * Kamera rollarini CSV orqali ommaviy belgilash (backend
 * app/services/camera_roles_csv.py): shablonni yuklab olish -> Excel'da
 * `xona_turi` va `xona_raqami` ni to'ldirish -> "Tekshirish" -> "Saqlash".
 */
export default function CameraRolesImportModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { token } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RolesImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleClose() {
    setFile(null);
    setResult(null);
    setError(null);
    onClose();
  }

  async function downloadTemplate() {
    setError(null);
    try {
      downloadBlob(await api.blob('/api/cameras/roles.csv', token), 'kamera-rollari.csv');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Shablonni yuklab bo'lmadi");
    }
  }

  async function send(apply: boolean) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api.postForm<RolesImportResult>(`/api/cameras/roles/import?apply=${apply}`, form, token);
      setResult(res);
      if (res.applied) onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Import xatosi');
    } finally {
      setBusy(false);
    }
  }

  const canSave = result !== null && !result.applied && result.changes.length > 0;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Xona turlari (CSV)"
      description="Xona turini ommaviy belgilash."
      size="lg"
      dismissible={!busy}
      footer={
        <>
          <Button onClick={handleClose} disabled={busy}>
            Yopish
          </Button>
          <Button icon={ScanSearch} onClick={() => send(false)} disabled={!file || busy} loading={busy && !canSave}>
            Tekshirish
          </Button>
          <Button variant="primary" icon={CheckCheck} onClick={() => send(true)} disabled={!canSave || busy} loading={busy && canSave}>
            Saqlash
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-[13px]">
        <ol className="list-decimal space-y-1.5 pl-5 text-fg">
          <li>Shablonni yuklab oling — unda barcha kameralar bor.</li>
          <li>
            Excel&apos;da <span className="font-mono text-xs">xona_turi</span> ({Object.keys(ROOM_TYPE_LABELS).join(', ')}) va{' '}
            <span className="font-mono text-xs">xona_raqami</span> ni to&apos;ldiring. Kirish kameralarida{' '}
            <span className="font-mono text-xs">yuz_yonalishi</span>: «kirish» — kamera kirayotganlarning yuzini
            ko&apos;radi, «chiqish» — chiqayotganlarnikini. Bo&apos;sh katak — o&apos;zgarmaydi, «-» — belgini olib tashlaydi.
          </li>
          <li>Faylni yuklab «Tekshirish», keyin «Saqlash».</li>
        </ol>
        <Notice tone="info">
          Xona turi AI modullarini yo&apos;naltiradi: uyqu faqat auditoriyada. Kunlik davomat kirish belgisini talab qilmaydi — kelish istalgan kameradagi birinchi
          ko&apos;rinish.
        </Notice>

        <Button icon={Download} onClick={downloadTemplate} className="w-fit">
          Shablonni yuklab olish
        </Button>

        <CsvDropzone
          file={file}
          placeholder="To'ldirilgan CSV faylni tanlang"
          onChange={(next) => {
            setFile(next);
            setResult(null);
          }}
        />

        {error && <Notice tone="danger">{error}</Notice>}

        {result && (
          <div className="flex flex-col gap-2">
            <Notice tone={result.applied ? 'success' : 'info'}>
              {result.rows} qator o&apos;qildi, {result.changes.length} ta o&apos;zgarish
              {result.applied ? ' saqlandi.' : ' — hali saqlanmagan.'}
            </Notice>
            {result.errors.length > 0 && (
              <Notice tone="danger" title={`${result.errors.length} ta qatorda xato`}>
                <ul className="max-h-28 space-y-1 overflow-y-auto">
                  {result.errors.map((err) => (
                    <li key={`${err.row}-${err.message}`}>
                      Qator {err.row}: {err.message}
                    </li>
                  ))}
                </ul>
              </Notice>
            )}
            {result.changes.length > 0 && (
              <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-control border border-border bg-surface-2 px-3">
                {result.changes.map((change) => (
                  <li key={`${change.cameraId}-${change.field}`} className="flex flex-wrap gap-x-2 py-1.5">
                    <span className="font-medium text-fg">{change.cameraName}</span>
                    <span className="text-muted">{FIELD_LABELS[change.field]}:</span>
                    <span className="text-subtle line-through">{show(change.field, change.old)}</span>
                    <span className="text-fg">→ {show(change.field, change.new)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
