import { useEffect, useState } from 'react';
import { Check, ImageOff, UserRoundX } from 'lucide-react';
import { Badge, Button, ErrorState, Modal } from '../../ui';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { StudentStaffRecord } from '../../types';

type Decision = 'approve' | 'reject';

interface Props {
  record: StudentStaffRecord | null;
  onClose: () => void;
  onDone: (decision: Decision, record: StudentStaffRecord) => void;
}

/**
 * Ochiq sahifada o'zini o'zi ro'yxatdan o'tkazgan odamning yuzini ko'rib
 * chiqish. Tasdiqlanmaguncha kameralar uni tanimaydi va "begona shaxs"
 * deb belgilaydi — tasdiqlash shuning uchun yuzni katta ko'rib, ism va
 * lavozim bilan solishtirgandan keyin qilinadi.
 */
export default function SelfEnrollmentReviewModal({ record, onClose, onDone }: Props) {
  const { token } = useAuth();
  const [pending, setPending] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (record) {
      setPending(null);
      setError(null);
    }
  }, [record]);

  async function decide(decision: Decision) {
    if (!record) return;
    setPending(decision);
    setError(null);
    try {
      const updated = await api.post<StudentStaffRecord>(`/api/students-staff/${record.id}/biometrics/${decision}`, {}, token);
      onDone(decision, updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Tarmoq xatosi');
      setPending(null);
    }
  }

  return (
    <Modal
      open={!!record}
      onClose={pending ? () => undefined : onClose}
      dismissible={!pending}
      title="Yuzni tasdiqlash"
      description="O'zini o'zi ro'yxatdan o'tkazgan. Tasdiqlansa, kameralar taniydi."
      size="sm"
      footer={
        <>
          <Button
            variant="secondary"
            icon={UserRoundX}
            onClick={() => decide('reject')}
            loading={pending === 'reject'}
            disabled={pending !== null}
            title="Rasm va yuz ma'lumoti o'chiriladi"
            className="text-danger hover:text-danger"
          >
            Rad etish
          </Button>
          <Button variant="primary" icon={Check} onClick={() => decide('approve')} loading={pending === 'approve'} disabled={pending !== null}>
            Tasdiqlash
          </Button>
        </>
      }
    >
      {record && (
        <div className="space-y-4">
          <div className="flex flex-col items-center gap-3 rounded-card border border-border bg-surface-2/60 p-4 text-center">
            {record.biometricPhotoUrl ? (
              <div className="flex items-end justify-center gap-2">
                {record.biometricPhotoLeftUrl && (
                  <img src={record.biometricPhotoLeftUrl} alt={`${record.fullName} — chap tomon`} className="h-28 w-28 rounded-card border border-border object-cover" />
                )}
                <img
                  src={record.biometricPhotoUrl}
                  alt={`${record.fullName} — yuborilgan yuz rasmi`}
                  className="h-40 w-40 rounded-card border border-border object-cover"
                />
                {record.biometricPhotoRightUrl && (
                  <img src={record.biometricPhotoRightUrl} alt={`${record.fullName} — o'ng tomon`} className="h-28 w-28 rounded-card border border-border object-cover" />
                )}
              </div>
            ) : (
              <div className="flex h-48 w-48 flex-col items-center justify-center gap-2 rounded-card bg-surface-3 text-sm text-muted">
                <ImageOff size={22} aria-hidden="true" />
                Rasm topilmadi
              </div>
            )}
            {record.hemisPhotoUrl && (
              <figure className="flex flex-col items-center gap-1">
                <img
                  src={record.hemisPhotoUrl}
                  alt={`${record.fullName} — HEMIS surati`}
                  referrerPolicy="no-referrer"
                  className="h-32 w-24 rounded-card border border-border object-cover"
                />
                <figcaption className="text-[11px] text-muted">HEMIS surati — solishtiring</figcaption>
              </figure>
            )}
            {record.reviewReason && (
              <p className="rounded-control border border-warning/40 bg-warning-soft px-2 py-1 text-[12px] text-fg">
                Tekshiruvga qoldi: {record.reviewReason}
              </p>
            )}
            <div className="min-w-0">
              <p className="text-base font-semibold text-fg">{record.fullName}</p>
              <p className="mt-1 flex flex-wrap items-center justify-center gap-1.5 text-xs text-muted">
                <Badge tone={record.type === 'talaba' ? 'primary' : 'info'}>{record.type === 'talaba' ? 'Talaba' : 'Xodim'}</Badge>
                {record.groupOrPosition}
                {record.faculty ? ` · ${record.faculty}` : ''}
              </p>
            </div>
          </div>
          {error && <ErrorState title="Qarorni saqlab bo'lmadi" message={error} />}
        </div>
      )}
    </Modal>
  );
}
