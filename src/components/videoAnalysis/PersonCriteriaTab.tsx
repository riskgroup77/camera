import { useEffect, useState } from 'react';
import { Badge, DataTable, IntelPanel, MicroLabel, type DataTableColumn } from '../../ui';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import {
  COAT_META,
  CRITERIA_NAMES,
  EARLY_LEAVE_META,
  clockOf,
  lessonsSummary,
  teacherSummary,
  videoAnalysisApi,
  type DailyCriteriaRow,
} from '../../lib/videoAnalysisApi';

/** Odam kartasidagi "Kriteriyalar" — kunlik video tahlil natijalari (oxirgi 30 kun). */
export default function PersonCriteriaTab({ personId, isStudent }: { personId: string; isStudent: boolean }) {
  const { token } = useAuth();
  const [rows, setRows] = useState<DailyCriteriaRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    videoAnalysisApi
      .person(personId, token)
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Natijalarni yuklab bo'lmadi");
      });
    return () => {
      cancelled = true;
    };
  }, [personId, token]);

  const columns: DataTableColumn<DailyCriteriaRow>[] = [
    { key: 'day', header: 'Kun', cell: (r) => <span className="tabular-nums font-medium">{r.day}</span> },
    {
      key: 'att',
      header: 'Davomat',
      cell: (r) =>
        r.attendanceStatus === 'kelmadi' ? (
          <Badge tone="danger" size="sm">Kelmadi</Badge>
        ) : r.attendanceStatus === 'kech_keldi' ? (
          <Badge tone="warning" size="sm">{r.lateMinutes ? `${r.lateMinutes} daq kech` : 'Kech'}</Badge>
        ) : r.attendanceStatus === 'keldi' ? (
          <Badge tone="success" size="sm">Keldi</Badge>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    { key: 'time', header: 'Keldi – ketdi', cell: (r) => <span className="tabular-nums text-[12px]">{clockOf(r.arrivedAt)} – {clockOf(r.leftAt)}</span> },
    {
      key: 'early',
      header: 'Erta ketish',
      cell: (r) =>
        r.earlyLeave && r.earlyLeave !== 'tegishli_emas' ? (
          <Badge tone={EARLY_LEAVE_META[r.earlyLeave].tone} size="sm">{EARLY_LEAVE_META[r.earlyLeave].label}</Badge>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    isStudent
      ? { key: 'lessons', header: 'Darslar', cell: (r) => <span className="text-[12px]">{lessonsSummary(r)}</span> }
      : { key: 'teacher', header: "Darslari", cell: (r) => <span className="text-[12px]">{teacherSummary(r)}</span> },
    isStudent
      ? { key: 'attention', header: 'Diqqat', align: 'right', cell: (r) => r.attentionScore ?? '—' }
      : { key: 'activity', header: 'Faollik', align: 'right', cell: (r) => r.teacherActivity ?? '—' },
    {
      key: 'coat',
      header: 'Oq xalat',
      cell: (r) =>
        r.coatStatus && r.coatStatus !== 'talab_yoq' ? (
          <Badge tone={COAT_META[r.coatStatus].tone} size="sm">{COAT_META[r.coatStatus].label}</Badge>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    {
      key: 'smoking',
      header: 'Chekish',
      align: 'right',
      cell: (r) => (r.smokingEvents ? <span className="font-medium text-danger">{r.smokingEvents}</span> : '—'),
    },
  ];

  return (
    <IntelPanel title="Kunlik video tahlil" right={<MicroLabel>oxirgi 30 kun</MicroLabel>}>
      <DataTable
        columns={columns}
        rows={rows ?? []}
        rowKey={(r) => r.day}
        loading={rows === null && !error}
        error={error}
        emptyTitle="Tahlil natijasi yo'q"
        emptyDescription="Bu odam oxirgi 30 kunda NVR yozuvlarida tanilmagan yoki tahlil hali bo'lmagan."
        ariaLabel="Kunlik kriteriyalar"
        maxHeight="none"
        dense
      />
      <EvidenceList rows={rows ?? []} />
    </IntelPanel>
  );
}

/** Aniqlangan holatlar kunlar bo'yicha: sabab, payt, kamera va 2 daqiqalik video dalil. */
function EvidenceList({ rows }: { rows: DailyCriteriaRow[] }) {
  const days = rows.filter((r) => r.evidence.length > 0);
  if (days.length === 0) return null;
  return (
    <section aria-label="Aniqlangan holatlar" className="mt-4 flex flex-col gap-4">
      <MicroLabel>Aniqlangan holatlar va video dalillar</MicroLabel>
      {days.map((r) => (
        <div key={r.day} className="flex flex-col gap-2">
          <p className="text-[13px] font-medium tabular-nums">{r.day}</p>
          <ul className="grid gap-3 sm:grid-cols-2">
            {r.evidence.map((e, index) => (
              <li key={`${e.at}-${e.code}-${index}`} className="flex min-w-0 flex-col gap-2 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="danger" size="sm">
                    {e.code}. {CRITERIA_NAMES[e.code] ?? 'Kriteriya'}
                  </Badge>
                  <span className="text-[12px] tabular-nums text-muted">
                    {clockOf(e.at)}
                    {e.cameraName ? ` · ${e.cameraName}` : ''}
                  </span>
                </div>
                <p className="text-[13px]">{e.reason}</p>
                {e.clipUrl ? (
                  <video
                    src={e.clipUrl}
                    controls
                    preload="none"
                    playsInline
                    className="aspect-video w-full rounded-md bg-black"
                    aria-label={`Video dalil: ${e.reason}`}
                  />
                ) : (
                  <p className="text-[12px] text-subtle">
                    {e.clipError ? `Video dalil yo'q: ${e.clipError}` : 'Video dalil tayyorlanmoqda'}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
