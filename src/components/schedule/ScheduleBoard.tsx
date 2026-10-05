import { useEffect, useMemo, useState, useRef } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { api, ApiError } from '../../lib/apiClient';
import { useVisibleInterval } from '../../lib/useVisibleInterval';
import { useAuth } from '../../lib/auth';
import { downloadBlob } from '../../lib/download';
import { todayInTashkent } from '../../lib/uzDate';
import PdfButton from '../situation/PdfButton';
import { Badge, Button, DataTable, EmptyState, ErrorState, Readout, useToast, type DataTableColumn } from '../../ui';
import DayOffNotice from '../situation/DayOffNotice';

/**
 * Kim qayerda bo'lishi kerak — HEMIS dars jadvali va kamera ko'rgan odamlar
 * (camera-api/app/services/schedule_presence.py).
 *
 * "Kamera ko'rmadi" — kelmagani degani emas: yuzi bazada bo'lmasa yoki
 * xona kamerasi burchagi yomon bo'lsa, odam kelgan bo'lsa ham ko'rinmaydi.
 */

export interface BoardRow {
  id: string;
  start: string | null;
  end: string | null;
  group: string;
  subject: string;
  faculty: string;
  teacher: string;
  teacherId: string | null;
  auditorium: string | null;
  building: string | null;
  cameraId: string | null;
  cameraName: string | null;
  teacherStatus: 'xonada' | 'binoda' | 'kelmagan' | null;
  studentsExpected: number;
  studentsArrived: number;
  studentsInRoom: number | null;
}

interface Board {
  day: string;
  now: boolean;
  items: BoardRow[];
}

const TEACHER_STATUS: Record<NonNullable<BoardRow['teacherStatus']>, { label: string; tone: 'success' | 'info' | 'danger' }> = {
  xonada: { label: 'Xonada', tone: 'success' },
  binoda: { label: 'Binoda', tone: 'info' },
  kelmagan: { label: "Kamera ko'rmadi", tone: 'danger' },
};

export function clock(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat('uz-UZ', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Tashkent' }).format(new Date(iso));
  } catch {
    return iso.slice(11, 16);
  }
}

export function todayTashkent(): string {
  return todayInTashkent();
}

export default function ScheduleBoard() {
  const { token } = useAuth();
  const toast = useToast();
  const [day, setDay] = useState(todayTashkent());
  const [nowOnly, setNowOnly] = useState(true);
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState('');
  const isToday = day === todayTashkent();

  // Boshqa kun yoki rejim tanlanganda eski jadval (va uning sonlari) yangi
  // javob kelguncha ko'rinib turmasin — yuklanish holati ko'rsatiladi.
  useEffect(() => {
    setBoard(null);
  }, [day, nowOnly]);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api
      .get<Board>(`/api/jadval/kun?sana=${day}&hozir=${nowOnly && isToday}`, undefined, { signal: controller.signal })
      .then(setBoard)
      .catch((err) => {
        if (controller.signal.aborted) return;
        setBoard(null);
        setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [day, nowOnly, isToday, reload]);

  // Ekran "bugun"da ochiq qolsa — yarim tundan keyin ham bugunga o'tadi
  // (aks holda "Faqat hozirgi darslar" kechagi kunda qotib qolardi).
  const lastToday = useRef(todayTashkent());
  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = todayTashkent();
      if (current === lastToday.current) return;
      setDay((shown) => (shown === lastToday.current ? current : shown));
      lastToday.current = current;
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  // Hozirgi darslar — daqiqada bir yangilanadi (kamera ko'rganlar o'zgarib boradi).
  // Yashirin oynada so'ramaydi (useVisibleInterval): butun kunlik jadval og'ir so'rov.
  useVisibleInterval(() => setReload((n) => n + 1), nowOnly && isToday ? 60_000 : null);

  const rows = useMemo(() => {
    const text = search.trim().toLowerCase();
    const items = board?.items ?? [];
    if (!text) return items;
    return items.filter((row) =>
      [row.group, row.subject, row.teacher, row.auditorium ?? '', row.building ?? ''].some((value) => value.toLowerCase().includes(text)),
    );
  }, [board, search]);

  const absentTeachers = rows.filter((row) => row.teacherStatus === 'kelmagan').length;
  const expected = rows.reduce((n, row) => n + row.studentsExpected, 0);
  const arrived = rows.reduce((n, row) => n + row.studentsArrived, 0);

  async function exportExcel() {
    try {
      const blob = await api.blob(`/api/jadval/kun.xlsx?sana=${day}&hozir=${nowOnly && isToday}`, token);
      downloadBlob(blob, `jadval-davomat-${day}.xlsx`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Yuklab bo'lmadi");
    }
  }

  const columns: DataTableColumn<BoardRow>[] = [
    { key: 'time', header: 'Vaqt', cell: (row) => `${clock(row.start)}–${clock(row.end)}`, sortValue: (row) => row.start ?? '' },
    { key: 'group', header: 'Guruh', sortValue: (row) => row.group, cell: (row) => <b>{row.group}</b> },
    { key: 'subject', header: 'Fan', sortValue: (row) => row.subject },
    {
      key: 'room',
      header: 'Xona',
      sortValue: (row) => `${row.building ?? ''} ${row.auditorium ?? ''}`,
      cell: (row) => (
        <span className="text-[13px]">
          {row.auditorium ?? '—'}
          <span className="block text-[11px] text-muted">
            {row.building ?? ''}
            {row.cameraName ? ` · kamera: ${row.cameraName}` : ' · kamerasiz'}
          </span>
        </span>
      ),
    },
    {
      key: 'teacher',
      header: "O'qituvchi",
      sortValue: (row) => row.teacherStatus ?? 'z',
      cell: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-[13px]">{row.teacher}</span>
          {row.teacherStatus ? (
            <Badge tone={TEACHER_STATUS[row.teacherStatus].tone}>{TEACHER_STATUS[row.teacherStatus].label}</Badge>
          ) : (
            <span className="text-[11px] text-muted">bazada topilmadi</span>
          )}
        </span>
      ),
    },
    {
      key: 'students',
      header: 'Talabalar',
      sortValue: (row) => (row.studentsExpected ? row.studentsArrived / row.studentsExpected : 0),
      cell: (row) => (
        <span className="text-[13px] tabular-nums">
          {row.studentsArrived}/{row.studentsExpected} keldi
          {row.studentsInRoom !== null && <span className="block text-[11px] text-muted">xonada ko&apos;rindi: {row.studentsInRoom}</span>}
        </span>
      ),
    },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border border-border bg-surface px-3 py-2">
        <Readout label="Darslar" value={board ? String(rows.length) : '—'} />
        <Readout label="O'qituvchini kamera ko'rmadi" value={board ? String(absentTeachers) : '—'} />
        <Readout label="Talabalar keldi" value={board && expected ? `${arrived}/${expected}` : '—'} />
        <span className="ms-auto flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={day}
            onChange={(event) => setDay(event.target.value || todayTashkent())}
            aria-label="Sana"
            className="h-8 rounded-control border border-border bg-surface px-2 text-[13px]"
          />
          {isToday && (
            <label className="flex items-center gap-1.5 text-[13px]">
              <input type="checkbox" checked={nowOnly} onChange={(event) => setNowOnly(event.target.checked)} />
              Faqat hozirgi darslar
            </label>
          )}
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Guruh, fan, o'qituvchi, xona"
            aria-label="Qidirish"
            className="h-8 w-56 rounded-control border border-border bg-surface px-2 text-[13px]"
          />
          <Button size="sm" icon={RefreshCw} onClick={() => setReload((n) => n + 1)}>
            Yangilash
          </Button>
          <Button size="sm" icon={Download} onClick={exportExcel}>
            Excel
          </Button>
          <PdfButton path="/api/jadval/kun.pdf" params={{ sana: day, hozir: String(nowOnly && isToday) }} filename={`jadval-davomat-${day}`} />
        </span>
      </div>
      <DayOffNotice date={day} onPick={(d) => { setNowOnly(false); setDay(d); }} />
      <p className="text-[12px] text-muted">
        &quot;Kamera ko&apos;rmadi&quot; — kelmagani degani emas: yuzi bazada bo&apos;lmasa yoki xona kamerasi burchagi yomon
        bo&apos;lsa, odam kelgan bo&apos;lsa ham ko&apos;rinmaydi.
      </p>
      {error ? (
        <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />
      ) : board && rows.length === 0 ? (
        <EmptyState
          title={nowOnly && isToday ? 'Hozir dars yo‘q' : 'Bu kunda dars yo‘q'}
          description="Dars jadvali HEMIS'dan har 3 soatda yangilanadi"
        />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.id} loading={!board} />
      )}
    </div>
  );
}
